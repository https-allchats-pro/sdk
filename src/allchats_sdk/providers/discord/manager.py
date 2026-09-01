from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import qrcode

from allchats_sdk.providers.common.proxy import requests_proxies_from_credentials
from allchats_sdk.providers.telegram.proxy_parse import normalize_proxy_config
from allchats_sdk.providers.discord.api import (
    avatar_url_from_user,
    display_name_from_user,
    get_current_user,
)
from allchats_sdk.config import Settings
from allchats_sdk.events import ChatsDiscoveredEvent, CredentialsUpdatedEvent, OutgoingMessageEvent
from allchats_sdk.protocols import EventSink, IncomingMessageHandler
from allchats_sdk.providers.credentials_cache import CredentialsCache
from allchats_sdk.credentials import discord_authorized, merge_credentials
from allchats_sdk.errors import ValidationError
from allchats_sdk.observability import record_auth

logger = logging.getLogger(__name__)


@dataclass
class DiscordAccountClient:
    account_id: str
    state_instance: str = "starting"
    user_id: str = ""
    error: str = ""
    running: bool = False
    auth_url: str = ""
    qr_status: str = ""
    stop_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False, compare=False)

    @property
    def is_authorized(self) -> bool:
        return self.state_instance == "authorized" or bool(str(self.user_id or "").strip())


class DiscordClientManager:
    def __init__(
        self,
        settings: Settings,
        event_sink: EventSink,
        incoming_handler: IncomingMessageHandler | None = None,
    ) -> None:
        self._settings = settings
        self._sink = event_sink
        self._creds = CredentialsCache()
        self._incoming_handler = incoming_handler
        self._clients: dict[str, DiscordAccountClient] = {}
        self._gateway_tasks: dict[str, asyncio.Task[None]] = {}
        self._gateway_ready: dict[str, bool] = {}
        self._qr_tasks: dict[str, asyncio.Task[None]] = {}
        self._login_tasks: dict[str, asyncio.Task[None]] = {}
        self._twofactor_queues: dict[str, asyncio.Queue[tuple[str, bool]]] = {}
        self._password_queues: dict[str, asyncio.Queue[str]] = {}
        self._captcha_queues: dict[str, asyncio.Queue[str]] = {}
        self._captcha_challenges: dict[str, dict[str, str]] = {}
        self._verification_hints: dict[str, str] = {}
        self._mfa_tickets: dict[str, str] = {}
        self._channel_meta: dict[str, dict[str, dict[str, Any]]] = {}
        self._gateway_outboxes: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._discord_library_clients: dict[str, Any] = {}
        self._voice_sessions: dict[str, dict[str, Any]] = {}
        # account_id -> user_id -> voice presence snapshot
        self._voice_presence: dict[str, dict[str, dict[str, Any]]] = {}
        self._voice_ssrc_by_user: dict[str, dict[int, str]] = {}
        self._voice_ws_tasks: dict[str, asyncio.Task[None]] = {}
        self._voice_ws_stops: dict[str, asyncio.Event] = {}
        self._voice_transports: dict[str, Any] = {}

    @property
    def event_sink(self) -> EventSink:
        return self._sink

    @property
    def api_base(self) -> str:
        return self._settings.discord.api_base

    @property
    def remote_auth_url(self) -> str:
        return self._settings.discord.remote_auth_url

    @property
    def gateway_url(self) -> str:
        return self._settings.discord.gateway_url

    @property
    def user_agent(self) -> str:
        return self._settings.discord.user_agent

    def proxy_url_from_proxies(self, proxies: dict[str, str] | None) -> str | None:
        if not proxies:
            return None
        return proxies.get("https") or proxies.get("http")

    async def account_credentials(self, account_id: str) -> dict[str, Any]:
        return self._creds.get_or_empty(account_id)

    def _global_proxy_config(self) -> dict[str, Any] | None:
        # Do NOT fall back to TELEGRAM_PROXY — that shared IP is often captcha'd by Discord.
        candidate = self._settings.discord.proxy
        if candidate is None or not candidate.is_configured():
            return None
        return normalize_proxy_config(
            {
                "type": candidate.type,
                "host": candidate.host,
                "port": candidate.port,
                "username": candidate.username,
                "password": candidate.password,
                "rdns": candidate.rdns,
            }
        )

    def requests_proxies(self, credentials: dict[str, Any]) -> dict[str, str] | None:
        return requests_proxies_from_credentials(
            credentials,
            global_config=self._global_proxy_config(),
        )

    def client_for_account(self, account_id: str) -> DiscordAccountClient | None:
        return self._clients.get(account_id)

    def set_gateway_ready(self, account_id: str, ready: bool) -> None:
        self._gateway_ready[account_id] = bool(ready)

    def is_gateway_ready(self, account_id: str) -> bool:
        return bool(self._gateway_ready.get(account_id))

    def channel_meta(self, account_id: str, channel_id: str) -> dict[str, Any] | None:
        return (self._channel_meta.get(account_id) or {}).get(channel_id)

    def set_channel_meta(self, account_id: str, channel_id: str, meta: dict[str, Any]) -> None:
        self._channel_meta.setdefault(account_id, {})[channel_id] = meta

    def gateway_outbox(self, account_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue = self._gateway_outboxes.get(account_id)
        if queue is None:
            queue = asyncio.Queue()
            self._gateway_outboxes[account_id] = queue
        return queue

    async def enqueue_gateway_payload(self, account_id: str, payload: dict[str, Any]) -> None:
        # Prefer discord.py-self websocket when available (voice state updates).
        library_client = self._discord_library_clients.get(account_id)
        ws = getattr(library_client, "ws", None) if library_client is not None else None
        if ws is not None and int(payload.get("op") or -1) == 4:
            data = payload.get("d") if isinstance(payload.get("d"), dict) else {}
            guild_raw = data.get("guild_id")
            channel_raw = data.get("channel_id")
            try:
                guild_id = int(guild_raw) if guild_raw not in (None, "") else None
                channel_id = int(channel_raw) if channel_raw not in (None, "") else None
                await ws.voice_state(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    self_mute=bool(data.get("self_mute", False)),
                    self_deaf=bool(data.get("self_deaf", False)),
                    self_video=bool(data.get("self_video", False)),
                )
                return
            except Exception:
                logger.exception(
                    "discord voice_state via selfcord failed account=%s",
                    account_id[:8],
                )
        await self.gateway_outbox(account_id).put(payload)

    def register_discord_library_client(self, account_id: str, client: Any) -> None:
        self._discord_library_clients[account_id] = client

    def unregister_discord_library_client(self, account_id: str, client: Any | None = None) -> None:
        current = self._discord_library_clients.get(account_id)
        if client is None or current is client:
            self._discord_library_clients.pop(account_id, None)

    def discord_library_client(self, account_id: str) -> Any | None:
        return self._discord_library_clients.get(account_id)

    def voice_session(self, account_id: str) -> dict[str, Any]:
        session = self._voice_sessions.get(account_id)
        if not session:
            return {"state": "idle", "channel_id": None, "guild_id": None}
        return dict(session)

    def update_voice_session(self, account_id: str, **fields: Any) -> dict[str, Any]:
        session = dict(self._voice_sessions.get(account_id) or {})
        session.update(fields)
        self._voice_sessions[account_id] = session
        return dict(session)

    def clear_voice_session(self, account_id: str) -> None:
        self._voice_sessions.pop(account_id, None)
        self.stop_voice_ws(account_id)
        self.clear_speaking_flags(account_id)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.stop_voice_audio(account_id))
        except RuntimeError:
            pass

    def set_voice_transport(self, account_id: str, transport: Any) -> None:
        previous = self._voice_transports.get(account_id)
        self._voice_transports[account_id] = transport
        if previous is not None and previous is not transport:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(previous.stop())
            except RuntimeError:
                pass

    def clear_voice_transport(self, account_id: str) -> None:
        self._voice_transports.pop(account_id, None)

    async def stop_voice_audio(self, account_id: str) -> None:
        transport = self._voice_transports.pop(account_id, None)
        if transport is not None:
            try:
                await transport.stop()
            except Exception:
                logger.warning("discord voice transport stop failed account=%s", account_id[:8])
        from allchats_sdk.providers.discord.voice_audio_bridge import detach_bridge

        await detach_bridge(account_id)

    def clear_voice_presence(self, account_id: str) -> None:
        self._voice_presence.pop(account_id, None)
        self._voice_ssrc_by_user.pop(account_id, None)

    def clear_speaking_flags(self, account_id: str) -> None:
        for state in (self._voice_presence.get(account_id) or {}).values():
            state["speaking"] = False
        self._voice_ssrc_by_user.pop(account_id, None)

    def set_user_speaking(
        self,
        account_id: str,
        user_id: str,
        *,
        speaking: bool,
        ssrc: int | None = None,
    ) -> None:
        user_key = str(user_id or "").strip()
        if not user_key:
            return
        if ssrc is not None:
            self._voice_ssrc_by_user.setdefault(account_id, {})[int(ssrc)] = user_key
        presence = self._voice_presence.setdefault(account_id, {})
        state = presence.get(user_key)
        if state is None:
            # Unknown user still speaking — keep a minimal card until VOICE_STATE catches up.
            state = {
                "user_id": user_key,
                "guild_id": str((self.voice_session(account_id) or {}).get("guild_id") or ""),
                "channel_id": str((self.voice_session(account_id) or {}).get("channel_id") or ""),
                "display_name": user_key,
                "avatar_url": None,
                "mute": False,
                "deaf": False,
                "self_mute": False,
                "self_deaf": False,
                "suppress": False,
            }
            presence[user_key] = state
        state["speaking"] = bool(speaking)
        if ssrc is not None:
            state["ssrc"] = int(ssrc)

    def resolve_voice_ssrc(self, account_id: str, ssrc: int) -> str:
        return str((self._voice_ssrc_by_user.get(account_id) or {}).get(int(ssrc)) or "").strip()

    def maybe_start_voice_ws(self, account_id: str) -> None:
        # Legacy custom voice WS path — superseded by discord.py-self VoiceClient
        # in voice_selfcord. Kept as a no-op so older call sites stay harmless.
        _ = account_id

    def stop_voice_ws(self, account_id: str) -> None:
        stop_event = self._voice_ws_stops.pop(account_id, None)
        if stop_event is not None:
            stop_event.set()
        task = self._voice_ws_tasks.pop(account_id, None)
        if task is not None and not task.done():
            task.cancel()

    def apply_voice_state_update(self, account_id: str, data: dict[str, Any]) -> None:
        user_id = str(data.get("user_id") or "").strip()
        if not user_id:
            return
        guild_id = str(data.get("guild_id") or "").strip()
        channel_raw = data.get("channel_id")
        channel_id = str(channel_raw).strip() if channel_raw not in (None, "") else ""
        presence = self._voice_presence.setdefault(account_id, {})
        if not channel_id:
            presence.pop(user_id, None)
            return

        member = data.get("member") if isinstance(data.get("member"), dict) else {}
        user = member.get("user") if isinstance(member.get("user"), dict) else {}
        if not user:
            user = {"id": user_id}
        nick = str(member.get("nick") or "").strip()
        display_name = nick or display_name_from_user(user) or user_id
        previous = presence.get(user_id) or {}
        presence[user_id] = {
            "user_id": user_id,
            "guild_id": guild_id,
            "channel_id": channel_id,
            "display_name": display_name,
            "avatar_url": avatar_url_from_user(user),
            "mute": bool(data.get("mute")),
            "deaf": bool(data.get("deaf")),
            "self_mute": bool(data.get("self_mute")),
            "self_deaf": bool(data.get("self_deaf")),
            "suppress": bool(data.get("suppress")),
            "speaking": bool(previous.get("speaking"))
            if str(previous.get("channel_id") or "") == channel_id
            else False,
            "ssrc": previous.get("ssrc"),
        }

    def ingest_guild_voice_states(
        self,
        account_id: str,
        guild_id: str,
        voice_states: list[Any] | None,
    ) -> None:
        if not guild_id or not isinstance(voice_states, list):
            return
        # Drop existing presence for this guild, then re-apply snapshot.
        presence = self._voice_presence.setdefault(account_id, {})
        for user_id, state in list(presence.items()):
            if str(state.get("guild_id") or "") == guild_id:
                presence.pop(user_id, None)
        for item in voice_states:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            if not payload.get("guild_id"):
                payload["guild_id"] = guild_id
            self.apply_voice_state_update(account_id, payload)

    def _meta_is_voice(self, meta: dict[str, Any] | None) -> bool:
        if not meta:
            return False
        channel_type = int(meta.get("channel_type") or -1)
        return bool(meta.get("is_voice")) or channel_type in {2, 13}

    async def _resolve_voice_channel_meta(
        self,
        account_id: str,
        channel_id: str,
    ) -> dict[str, Any]:
        """Return voice-channel meta from cache or live discord.py-self client."""
        external_chat_id = channel_id.strip()
        meta = dict(self.channel_meta(account_id, external_chat_id) or {})
        if self._meta_is_voice(meta) and str(meta.get("guild_id") or "").strip():
            return meta

        client = self.discord_library_client(account_id)
        if client is None:
            if self._meta_is_voice(meta):
                return meta
            raise ValidationError("channel is not a voice channel")

        try:
            snowflake = int(external_chat_id)
        except ValueError as exc:
            raise ValidationError("channel is not a voice channel") from exc

        import discord

        channel = client.get_channel(snowflake)
        if channel is None:
            try:
                channel = await client.fetch_channel(snowflake)
            except Exception as exc:
                logger.debug(
                    "discord fetch voice channel failed account=%s channel=%s err=%r",
                    account_id[:8],
                    external_chat_id,
                    exc,
                )
                channel = None

        if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            raise ValidationError("channel is not a voice channel")

        guild = getattr(channel, "guild", None)
        guild_id = str(getattr(guild, "id", "") or "").strip() or str(meta.get("guild_id") or "")
        guild_name = (
            str(getattr(guild, "name", "") or "").strip() or str(meta.get("guild_name") or "")
        )
        channel_type = self._channel_type_value(channel)
        resolved = {
            "id": external_chat_id,
            "title": str(getattr(channel, "name", "") or external_chat_id),
            "is_group": True,
            "avatar_url": None,
            "channel_type": channel_type,
            "guild_id": guild_id or None,
            "guild_name": guild_name or None,
            "parent_id": str(getattr(channel, "category_id", None) or "") or None,
            "position": int(getattr(channel, "position", 0) or 0),
            "is_voice": True,
        }
        self.set_channel_meta(account_id, external_chat_id, resolved)
        return resolved

    async def list_voice_members(self, account_id: str, channel_id: str) -> list[dict[str, Any]]:
        credentials = await self.account_credentials(account_id)
        if not discord_authorized(credentials):
            raise ValidationError("discord account is not authorized")
        external_chat_id = channel_id.strip()
        await self._resolve_voice_channel_meta(account_id, external_chat_id)

        members = []
        for state in (self._voice_presence.get(account_id) or {}).values():
            if str(state.get("channel_id") or "") != external_chat_id:
                continue
            item = dict(state)
            item["speaking"] = bool(item.get("speaking"))
            members.append(item)
        members.sort(
            key=lambda item: (
                0 if item.get("speaking") else 1,
                str(item.get("display_name") or item.get("user_id") or "").lower(),
            )
        )
        return members

    def verification_hint_for_account(self, account_id: str) -> str:
        return self._verification_hints.get(account_id, "")

    def is_qr_auth_active(self, account_id: str) -> bool:
        task = self._qr_tasks.get(account_id)
        return task is not None and not task.done()

    def unregister_client(self, account_id: str) -> None:
        self._clients.pop(account_id, None)

    def set_client_state(
        self,
        account_id: str,
        *,
        state_instance: str,
        user_id: str = "",
        error: str = "",
        running: bool = True,
    ) -> DiscordAccountClient:
        client = self._clients.get(account_id)
        if client is None:
            client = DiscordAccountClient(account_id=account_id)
            self._clients[account_id] = client
        client.state_instance = state_instance
        if user_id:
            client.user_id = user_id
        client.error = error
        client.running = running
        return client

    async def start_qr(
        self,
        account_id: str,
        *,
        refresh: bool = False,
    ) -> DiscordAccountClient:
        if refresh:
            await self.stop_qr(account_id)

        if not refresh:
            task = self._qr_tasks.get(account_id)
            client = self._clients.get(account_id)
            if task is not None and not task.done() and client is not None and client.auth_url:
                return client

        await self.cancel_login_auth(account_id)
        client = self.set_client_state(account_id, state_instance="starting", running=True)
        client.auth_url = ""
        client.qr_status = ""

        from allchats_sdk.providers.discord.qr_auth_worker import run_discord_qr_auth_worker

        credentials = await self.account_credentials(account_id)
        proxies = self.requests_proxies(credentials)
        task = asyncio.create_task(
            run_discord_qr_auth_worker(
                account_id,
                manager=self,
                client=client,
                proxies=proxies,
            ),
            name=f"discord-qr-{account_id[:8]}",
        )
        self._qr_tasks[account_id] = task
        task.add_done_callback(lambda _task: self._qr_tasks.pop(account_id, None))

        deadline = time.time() + 30.0
        while time.time() < deadline:
            if client.auth_url:
                return client
            if client.state_instance == "authorized" or client.is_authorized:
                return client
            if client.error and client.state_instance == "notAuthorized":
                raise ValidationError(client.error or "discord qr auth failed")
            await asyncio.sleep(0.25)

        if client.error:
            raise ValidationError(client.error)
        raise ValidationError("qr not available: discord did not respond in time")

    @staticmethod
    def _qr_data_url(qr_link: str) -> str:
        if not qr_link:
            return ""
        image = qrcode.make(qr_link)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    @staticmethod
    def to_qr_response(client: DiscordAccountClient) -> dict[str, Any]:
        return {
            "type": "qrCode",
            "qr_link": client.auth_url,
            "data_url": DiscordClientManager._qr_data_url(client.auth_url),
            "polling_interval": 2,
            "qr_status": client.qr_status,
        }

    def cleanup_qr_auth(self, account_id: str) -> None:
        self._qr_tasks.pop(account_id, None)

    async def stop_qr(self, account_id: str) -> None:
        task = self._qr_tasks.pop(account_id, None)
        client = self._clients.get(account_id)
        if client is not None:
            client.running = False
            client.auth_url = ""
            client.qr_status = ""
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("discord qr cancel failed account=%s: %s", account_id[:8], exc)
        self.cleanup_qr_auth(account_id)

    async def start_login_auth(
        self,
        account_id: str,
        *,
        login: str,
        password: str,
    ) -> None:
        login = login.strip()
        password = password.strip()
        if not login:
            raise ValidationError("login is required")
        if not password:
            raise ValidationError("password is required")

        await self.cancel_login_auth(account_id)
        await self.stop_qr(account_id)
        self.set_client_state(account_id, state_instance="starting", running=True)

        from allchats_sdk.providers.discord.login_auth_worker import run_discord_login_auth_worker

        credentials = await self.account_credentials(account_id)
        proxies = self.requests_proxies(credentials)
        self._login_tasks[account_id] = asyncio.create_task(
            run_discord_login_auth_worker(
                account_id,
                login_value=login,
                password=password,
                manager=self,
                proxies=proxies,
            ),
            name=f"discord-login-{account_id[:8]}",
        )

    async def wait_verification_code(
        self,
        account_id: str,
        *,
        kind: str,
        hint: str = "",
    ) -> tuple[str, bool]:
        state = "mfaRequired" if kind == "mfa" else "passwordRequired"
        if hint:
            self._verification_hints[account_id] = hint
        self.set_client_state(account_id, state_instance=state, running=True)
        queue = self._twofactor_queues.setdefault(account_id, asyncio.Queue())
        return await asyncio.wait_for(queue.get(), timeout=300.0)

    async def submit_2fa_code(self, account_id: str, *, code: str) -> None:
        raw = code.strip()
        if not raw:
            raise ValidationError("code is required")
        queue = self._twofactor_queues.get(account_id)
        if queue is None:
            raise ValidationError("verification code is not required")
        await queue.put((raw, False))

    async def wait_password(self, account_id: str, *, hint: str = "") -> str:
        if hint:
            self._verification_hints[account_id] = hint
        self.set_client_state(account_id, state_instance="passwordRequired", running=True)
        queue = self._password_queues.setdefault(account_id, asyncio.Queue())
        return await asyncio.wait_for(queue.get(), timeout=300.0)

    async def submit_password(self, account_id: str, *, password: str) -> None:
        raw = password.strip()
        if not raw:
            raise ValidationError("password is required")
        queue = self._password_queues.get(account_id)
        if queue is None:
            raise ValidationError("password is not required")
        await queue.put(raw)

    def captcha_challenge_for_account(self, account_id: str) -> dict[str, str] | None:
        challenge = self._captcha_challenges.get(account_id)
        return dict(challenge) if challenge else None

    async def wait_captcha_solution(
        self,
        account_id: str,
        challenge: dict[str, str],
    ) -> str:
        self._captcha_challenges[account_id] = dict(challenge)
        self.set_client_state(account_id, state_instance="captchaRequired", running=True)
        queue = self._captcha_queues.setdefault(account_id, asyncio.Queue())
        # Drop stale solutions from a previous challenge.
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        solution = await asyncio.wait_for(queue.get(), timeout=300.0)
        return solution

    async def submit_captcha(self, account_id: str, *, captcha_key: str) -> None:
        raw = captcha_key.strip()
        if not raw:
            raise ValidationError("captcha_key is required")
        queue = self._captcha_queues.get(account_id)
        if queue is None:
            raise ValidationError("captcha is not required")
        await queue.put(raw)

    def cleanup_login_auth(self, account_id: str) -> None:
        self._twofactor_queues.pop(account_id, None)
        self._password_queues.pop(account_id, None)
        self._captcha_queues.pop(account_id, None)
        self._captcha_challenges.pop(account_id, None)
        self._verification_hints.pop(account_id, None)
        self._mfa_tickets.pop(account_id, None)
        self._login_tasks.pop(account_id, None)

    async def cancel_login_auth(self, account_id: str) -> None:
        task = self._login_tasks.pop(account_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("discord login cancel failed account=%s: %s", account_id[:8], exc)
        self.cleanup_login_auth(account_id)

    async def finalize_auth(
        self,
        account_id: str,
        *,
        token: str,
        auth_method: str,
    ) -> dict[str, Any]:
        token = token.strip()
        if not token:
            raise ValidationError("token is required")

        credentials = await self.account_credentials(account_id)
        proxies = self.requests_proxies(credentials)
        me = await get_current_user(
            api_base=self.api_base,
            token=token,
            proxies=proxies,
            user_agent=self.user_agent,
        )
        user_id = str(me.get("id") or "").strip()
        if not user_id:
            raise ValidationError("failed to resolve discord user id")

        nickname = display_name_from_user(me) or None
        avatar_url = avatar_url_from_user(me)
        incoming = {
            "device_id": account_id,
            "user_id": user_id,
            "token": token,
            "auth_method": auth_method,
            "state_instance": "authorized",
        }
        if avatar_url:
            incoming["avatar_url"] = avatar_url

        merged = merge_credentials(credentials, incoming)
        self._creds.set(account_id, merged)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="discord",
                credentials=merged,
                user_id=user_id,
                nickname=nickname,
            )
        )
        client = self.set_client_state(
            account_id,
            state_instance="authorized",
            user_id=user_id,
            running=True,
        )
        client.auth_url = ""
        client.qr_status = ""
        client.error = ""

        await self._sync_and_start_gateway(account_id, merged)
        record_auth("discord", "ok")
        return merged

    async def ensure_gateway(self, account_id: str, credentials: dict[str, Any]) -> DiscordAccountClient:
        if not discord_authorized(credentials):
            raise ValidationError("account is not authorized")
        self._creds.set(account_id, credentials)
        token = str(credentials.get("token") or "").strip()
        user_id = str(credentials.get("user_id") or "").strip()
        client = self.set_client_state(
            account_id,
            state_instance="authorized",
            user_id=user_id,
            running=True,
        )
        task = self._gateway_tasks.get(account_id)
        if task is not None and not task.done():
            return client
        await self._sync_and_start_gateway(account_id, credentials)
        return client

    async def connect_account(self, account_id: str, credentials: dict[str, Any]) -> DiscordAccountClient:
        return await self.ensure_gateway(account_id, credentials)

    async def sync_channels_for_account(self, account_id: str) -> int:
        # Bulk DB sync disabled — live guild/channel APIs + open_channel instead.
        _ = account_id
        return 0

    async def _wait_library_client_ready(self, account_id: str, *, timeout_sec: float = 15.0) -> None:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if self.is_gateway_ready(account_id) and self.discord_library_client(account_id) is not None:
                return
            await asyncio.sleep(0.25)
        raise ValidationError("discord client is not ready")

    def _channel_type_value(self, channel: Any) -> int:
        raw = getattr(channel, "type", 0)
        return int(getattr(raw, "value", raw) or 0)

    def _collect_channels_from_client(self, account_id: str) -> list[dict[str, Any]]:
        client = self.discord_library_client(account_id)
        if client is None:
            raise ValidationError("discord client is not connected")

        channels: list[dict[str, Any]] = []

        # Guild channels only — DMs / group DMs are not listed in the operator sidebar.
        for guild in list(getattr(client, "guilds", []) or []):
            guild_id = str(getattr(guild, "id", "") or "").strip()
            guild_name = str(getattr(guild, "name", "") or "").strip() or guild_id
            for channel in list(getattr(guild, "channels", []) or []):
                channel_id = str(getattr(channel, "id", "") or "").strip()
                if not channel_id:
                    continue
                channel_type = self._channel_type_value(channel)
                # Keep text/voice/category/announcement/stage (0, 2, 4, 5, 13).
                if channel_type not in {0, 2, 4, 5, 13}:
                    continue
                name = str(getattr(channel, "name", "") or channel_id).strip() or channel_id
                is_voice = channel_type in {2, 13}
                is_category = channel_type == 4
                parent = getattr(channel, "category_id", None) or getattr(channel, "parent_id", None)
                parent_id = str(parent).strip() if parent not in (None, "") else None
                if is_category or is_voice:
                    title = name
                else:
                    title = f"#{name}"
                channels.append(
                    {
                        "id": channel_id,
                        "title": title,
                        "is_group": True,
                        "avatar_url": None,
                        "channel_type": channel_type,
                        "guild_id": guild_id,
                        "guild_name": guild_name,
                        "parent_id": None if is_category else parent_id,
                        "position": int(getattr(channel, "position", 0) or 0),
                        "is_voice": is_voice,
                    }
                )
        return channels

    async def list_guilds(self, account_id: str) -> list[dict[str, Any]]:
        credentials = await self.account_credentials(account_id)
        if not discord_authorized(credentials):
            raise ValidationError("discord account is not authorized")
        await self._wait_library_client_ready(account_id, timeout_sec=20.0)
        client = self.discord_library_client(account_id)
        if client is None:
            raise ValidationError("discord client is not connected")
        guilds: list[dict[str, Any]] = []
        for guild in list(getattr(client, "guilds", []) or []):
            guild_id = str(getattr(guild, "id", "") or "").strip()
            if not guild_id:
                continue
            guilds.append(
                {
                    "id": guild_id,
                    "name": str(getattr(guild, "name", "") or "").strip() or guild_id,
                }
            )
        guilds.sort(key=lambda item: str(item.get("name") or "").lower())
        return guilds

    async def list_guild_channels(self, account_id: str, guild_id: str) -> list[dict[str, Any]]:
        credentials = await self.account_credentials(account_id)
        if not discord_authorized(credentials):
            raise ValidationError("discord account is not authorized")
        guild_key = str(guild_id or "").strip()
        if not guild_key:
            raise ValidationError("guild_id is required")
        await self._wait_library_client_ready(account_id, timeout_sec=20.0)
        client = self.discord_library_client(account_id)
        if client is None:
            raise ValidationError("discord client is not connected")
        try:
            snowflake = int(guild_key)
        except ValueError as exc:
            raise ValidationError("guild_id is invalid") from exc
        guild = client.get_guild(snowflake)
        if guild is None:
            raise ValidationError("guild not found")
        guild_name = str(getattr(guild, "name", "") or "").strip() or guild_key
        channels: list[dict[str, Any]] = []
        for channel in list(getattr(guild, "channels", []) or []):
            channel_id = str(getattr(channel, "id", "") or "").strip()
            if not channel_id:
                continue
            channel_type = self._channel_type_value(channel)
            if channel_type not in {0, 2, 4, 5, 13}:
                continue
            name = str(getattr(channel, "name", "") or channel_id).strip() or channel_id
            is_voice = channel_type in {2, 13}
            is_category = channel_type == 4
            parent = getattr(channel, "category_id", None) or getattr(channel, "parent_id", None)
            parent_id = str(parent).strip() if parent not in (None, "") else None
            channels.append(
                {
                    "id": channel_id,
                    "title": name if (is_category or is_voice) else f"#{name}",
                    "is_group": True,
                    "channel_type": channel_type,
                    "guild_id": guild_key,
                    "guild_name": guild_name,
                    "parent_id": None if is_category else parent_id,
                    "position": int(getattr(channel, "position", 0) or 0),
                    "is_voice": is_voice,
                }
            )
        channels.sort(
            key=lambda item: (
                0 if int(item.get("channel_type") or 0) == 4 else 1,
                int(item.get("position") or 0),
                str(item.get("title") or ""),
            )
        )
        return channels

    async def get_live_channel(self, account_id: str, channel_id: str) -> dict[str, Any]:
        credentials = await self.account_credentials(account_id)
        if not discord_authorized(credentials):
            raise ValidationError("discord account is not authorized")
        await self._wait_library_client_ready(account_id, timeout_sec=20.0)
        client = self.discord_library_client(account_id)
        if client is None:
            raise ValidationError("discord client is not connected")
        external = str(channel_id or "").strip()
        if not external:
            raise ValidationError("channel_id is required")
        try:
            snowflake = int(external)
        except ValueError as exc:
            raise ValidationError("channel_id is invalid") from exc
        channel = client.get_channel(snowflake)
        if channel is None:
            try:
                channel = await client.fetch_channel(snowflake)
            except Exception as exc:
                raise ValidationError("channel not found") from exc
        channel_type = self._channel_type_value(channel)
        if channel_type not in {0, 2, 5, 13}:
            raise ValidationError("channel is not a text or voice channel")
        guild = getattr(channel, "guild", None)
        guild_id = str(getattr(guild, "id", "") or "").strip()
        guild_name = str(getattr(guild, "name", "") or "").strip() or guild_id
        name = str(getattr(channel, "name", "") or external).strip() or external
        is_voice = channel_type in {2, 13}
        parent = getattr(channel, "category_id", None) or getattr(channel, "parent_id", None)
        parent_id = str(parent).strip() if parent not in (None, "") else None
        payload = {
            "id": external,
            "title": name if is_voice else f"#{name}",
            "is_group": True,
            "channel_type": channel_type,
            "guild_id": guild_id or None,
            "guild_name": guild_name or None,
            "parent_id": parent_id,
            "position": int(getattr(channel, "position", 0) or 0),
            "is_voice": is_voice,
        }
        self.set_channel_meta(account_id, external, dict(payload))
        return payload

    async def join_voice(self, account_id: str, channel_id: str) -> dict[str, Any]:
        credentials = await self.account_credentials(account_id)
        if not discord_authorized(credentials):
            raise ValidationError("discord account is not authorized")
        external_chat_id = channel_id.strip()

        task = self._gateway_tasks.get(account_id)
        if task is None or task.done():
            await self.ensure_gateway(account_id, credentials)

        if not self.is_gateway_ready(account_id):
            for _ in range(40):
                if self.is_gateway_ready(account_id):
                    break
                await asyncio.sleep(0.25)
            if not self.is_gateway_ready(account_id):
                return self.update_voice_session(
                    account_id,
                    state="error",
                    channel_id=external_chat_id,
                    guild_id="",
                    endpoint="",
                    token="",
                    session_id="",
                    error="discord gateway offline (check proxy / Discord connectivity)",
                )

        meta = await self._resolve_voice_channel_meta(account_id, external_chat_id)
        guild_id = str(meta.get("guild_id") or "").strip()
        if not guild_id:
            raise ValidationError("voice channel guild_id is missing")

        # Tear down any legacy custom voice WS / previous VoiceClient session.
        self.stop_voice_ws(account_id)
        await self.stop_voice_audio(account_id)

        self.update_voice_session(
            account_id,
            state="joining",
            channel_id=external_chat_id,
            guild_id=guild_id,
            endpoint="",
            token="",
            session_id="",
            error="",
        )
        try:
            from allchats_sdk.providers.discord.voice_selfcord import start_selfcord_voice_session

            await start_selfcord_voice_session(
                account_id,
                manager=self,
                channel_id=external_chat_id,
            )
        except Exception as exc:
            logger.exception(
                "discord selfcord voice join failed account=%s channel=%s",
                account_id[:8],
                external_chat_id,
            )
            await self.stop_voice_audio(account_id)
            return self.update_voice_session(
                account_id,
                state="error",
                channel_id=external_chat_id,
                guild_id=guild_id,
                error=str(exc) or "discord voice join failed",
            )
        return self.voice_session(account_id)

    async def leave_voice(self, account_id: str) -> dict[str, Any]:
        session = self._voice_sessions.get(account_id)
        if not session:
            return {"state": "idle", "channel_id": None, "guild_id": None}
        await self.stop_voice_audio(account_id)
        self._voice_sessions.pop(account_id, None)
        self.stop_voice_ws(account_id)
        self.clear_speaking_flags(account_id)
        return {"state": "idle", "channel_id": None, "guild_id": None}

    async def _sync_and_start_gateway(self, account_id: str, credentials: dict[str, Any]) -> None:
        token = str(credentials.get("token") or "").strip()
        if not token:
            raise ValidationError("discord token is required")

        # Start gateway first so voice/join is not blocked by channel sync via HTTP proxy.
        await self.stop_gateway(account_id)
        client = self.set_client_state(
            account_id,
            state_instance="authorized",
            user_id=str(credentials.get("user_id") or ""),
            running=True,
        )
        client.stop_event = asyncio.Event()

        from allchats_sdk.providers.discord.selfcord_runtime import run_discord_selfcord_runtime

        task = asyncio.create_task(
            run_discord_selfcord_runtime(
                account_id,
                manager=self,
                token=token,
                stop_event=client.stop_event,
            ),
            name=f"discord-selfcord-{account_id[:8]}",
        )
        self._gateway_tasks[account_id] = task
        task.add_done_callback(lambda _task: self._gateway_tasks.pop(account_id, None))
        # Do not bulk-sync every guild channel into chats — sidebar uses live
        # guild/channel listing; DB rows are created only when a channel is opened.

    async def stop_gateway(self, account_id: str) -> None:
        client = self._clients.get(account_id)
        if client is not None:
            client.stop_event.set()
            client.running = False
        task = self._gateway_tasks.pop(account_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("discord gateway stop failed account=%s: %s", account_id[:8], exc)
        self._gateway_outboxes.pop(account_id, None)
        self._gateway_ready.pop(account_id, None)
        self._discord_library_clients.pop(account_id, None)

    async def disconnect(self, account_id: str) -> None:
        await self.cancel_login_auth(account_id)
        await self.stop_qr(account_id)
        await self.stop_gateway(account_id)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="discord",
                credentials={},
                clear=True,
            )
        )
        self._creds.pop(account_id)
        self._channel_meta.pop(account_id, None)
        self.clear_voice_session(account_id)
        self.clear_voice_presence(account_id)
        self.unregister_client(account_id)

    async def send_message(
        self,
        account_id: str,
        *,
        text: str,
        chat_id: str,
        reply_to_external_id: str | None = None,
    ) -> tuple[str, str]:
        trimmed = text.strip()
        if not trimmed:
            raise ValidationError("text is required")
        if not chat_id.strip():
            raise ValidationError("chat_id is required")

        credentials = self._creds.get(account_id)
        if not discord_authorized(credentials):
            raise ValidationError("discord account is not authorized")

        external_chat_id = chat_id.strip()
        meta = self.channel_meta(account_id, external_chat_id) or {}
        if self._meta_is_voice(meta):
            raise ValidationError("cannot send text messages to a voice channel")

        await self._wait_library_client_ready(account_id)
        library_client = self.discord_library_client(account_id)
        if library_client is None:
            raise ValidationError("discord client is not connected")

        try:
            import discord

            channel = library_client.get_channel(int(external_chat_id))
            if channel is None:
                channel = await library_client.fetch_channel(int(external_chat_id))
            kwargs: dict[str, Any] = {"content": trimmed}
            if reply_to_external_id:
                kwargs["reference"] = discord.MessageReference(
                    message_id=int(reply_to_external_id),
                    channel_id=int(external_chat_id),
                    fail_if_not_exists=False,
                )
            sent = await channel.send(**kwargs)
            message_id = str(getattr(sent, "id", "") or "").strip()
        except Exception as exc:
            raise ValidationError(f"failed to send discord message: {exc}") from exc

        if not message_id:
            raise ValidationError("discord send returned empty message id")

        from_id = str(credentials.get("user_id") or account_id)
        meta = self.channel_meta(account_id, external_chat_id) or {}
        is_group = bool(meta.get("is_group", True))

        await self._sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="discord",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                text=trimmed,
                from_id=from_id,
                sent_at=datetime.now(UTC),
                is_group=is_group,
                metadata={"emit_ws": False},
            )
        )
        return message_id, external_chat_id

    async def add_reaction(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
        emoji: str,
    ) -> None:
        message = await self._fetch_message(
            account_id,
            chat_id=chat_id,
            external_message_id=external_message_id,
        )
        try:
            await message.add_reaction(emoji)
        except Exception as exc:
            raise ValidationError(f"failed to add discord reaction: {exc}") from exc

    async def remove_reaction(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
        emoji: str,
    ) -> None:
        message = await self._fetch_message(
            account_id,
            chat_id=chat_id,
            external_message_id=external_message_id,
        )
        library_client = self.discord_library_client(account_id)
        user = getattr(library_client, "user", None) if library_client is not None else None
        try:
            await message.remove_reaction(emoji, user)
        except Exception as exc:
            raise ValidationError(f"failed to remove discord reaction: {exc}") from exc

    async def delete_message(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
    ) -> None:
        message = await self._fetch_message(
            account_id,
            chat_id=chat_id,
            external_message_id=external_message_id,
        )
        try:
            await message.delete()
        except Exception as exc:
            raise ValidationError(f"failed to delete discord message: {exc}") from exc

    async def _fetch_message(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
    ) -> Any:
        credentials, _token, external_chat_id = await self._require_send_context(
            account_id,
            chat_id=chat_id,
        )
        del credentials
        await self._wait_library_client_ready(account_id)
        library_client = self.discord_library_client(account_id)
        if library_client is None:
            raise ValidationError("discord client is not connected")
        try:
            channel = library_client.get_channel(int(external_chat_id))
            if channel is None:
                channel = await library_client.fetch_channel(int(external_chat_id))
            return await channel.fetch_message(int(external_message_id))
        except Exception as exc:
            raise ValidationError(f"failed to resolve discord message: {exc}") from exc

    async def _require_send_context(
        self,
        account_id: str,
        *,
        chat_id: str,
    ) -> tuple[dict[str, Any], str, str]:
        credentials = self._creds.get(account_id)
        if not discord_authorized(credentials):
            raise ValidationError("discord account is not authorized")
        token = str(credentials.get("token") or "").strip()
        external_chat_id = chat_id.strip()
        return credentials, token, external_chat_id
