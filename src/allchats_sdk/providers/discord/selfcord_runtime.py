"""Discord user-client runtime backed by discord.py-self.

Handles messaging via Client events and tracks VOICE_* presence for the
VoiceClient-backed voice session (see voice_selfcord).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from allchats_sdk.events import IncomingMessageEvent, OutgoingMessageEvent

if TYPE_CHECKING:
    from allchats_sdk.providers.discord.manager import DiscordClientManager

logger = logging.getLogger(__name__)


def _proxy_kwargs(proxy_url: str | None) -> dict[str, Any]:
    if not proxy_url:
        return {}
    parsed = urlparse(proxy_url)
    kwargs: dict[str, Any] = {"proxy": proxy_url, "proxy_gateway": True}
    if parsed.username or parsed.password:
        try:
            from aiohttp import BasicAuth
        except ImportError:
            return kwargs
        kwargs["proxy_auth"] = BasicAuth(
            parsed.username or "",
            parsed.password or "",
        )
    return kwargs


def _message_sent_at(message: Any) -> datetime:
    created = getattr(message, "created_at", None)
    if isinstance(created, datetime):
        if created.tzinfo is None:
            return created.replace(tzinfo=UTC)
        return created.astimezone(UTC)
    return datetime.now(UTC)


def _author_display_name(author: Any) -> str:
    if author is None:
        return ""
    for attr in ("display_name", "global_name", "name"):
        value = getattr(author, attr, None)
        if value:
            return str(value)
    return str(getattr(author, "id", "") or "")


async def run_discord_selfcord_runtime(
    account_id: str,
    *,
    manager: DiscordClientManager,
    token: str,
    stop_event: asyncio.Event,
) -> None:
    import discord

    backoff_sec = 1.0
    while not stop_event.is_set():
        manager.set_gateway_ready(account_id, False)
        proxy_url: str | None = None
        try:
            credentials = await manager.account_credentials(account_id)
            proxy_url = manager.proxy_url_from_proxies(manager.requests_proxies(credentials))
        except Exception as exc:
            logger.warning(
                "discord selfcord proxy resolve failed account=%s: %s",
                account_id[:8],
                exc,
            )

        client = discord.Client(
            chunk_guilds_at_startup=False,
            enable_debug_events=True,
            **_proxy_kwargs(proxy_url),
        )
        manager.register_discord_library_client(account_id, client)

        @client.event
        async def on_ready() -> None:  # noqa: WPS430 — nested event handler
            nonlocal backoff_sec
            user = client.user
            user_id = str(getattr(user, "id", "") or "").strip()
            if user_id:
                manager.set_client_state(
                    account_id,
                    state_instance="authorized",
                    user_id=user_id,
                    running=True,
                )
            manager.set_gateway_ready(account_id, True)
            backoff_sec = 1.0
            logger.info(
                "discord selfcord ready account=%s user=%s proxy=%s",
                account_id[:8],
                user_id[:8] if user_id else "-",
                "yes" if proxy_url else "direct",
            )
            for guild in list(client.guilds):
                try:
                    voice_states = [
                        {
                            "user_id": str(member.id),
                            "channel_id": str(member.voice.channel.id)
                            if member.voice and member.voice.channel
                            else None,
                            "session_id": getattr(member.voice, "session_id", None),
                            "self_mute": bool(getattr(member.voice, "self_mute", False)),
                            "self_deaf": bool(getattr(member.voice, "self_deaf", False)),
                        }
                        for member in guild.members
                        if getattr(member, "voice", None) is not None
                    ]
                    manager.ingest_guild_voice_states(
                        account_id,
                        str(guild.id),
                        voice_states,
                    )
                except Exception:
                    logger.debug(
                        "discord voice state ingest skipped account=%s guild=%s",
                        account_id[:8],
                        getattr(guild, "id", "?"),
                        exc_info=True,
                    )

        @client.event
        async def on_message(message: Any) -> None:  # noqa: WPS430
            await _emit_message_event(account_id, manager, client, message)

        @client.event
        async def on_socket_raw_receive(payload: Any) -> None:  # noqa: WPS430
            await _handle_raw_gateway_event(account_id, manager, payload)

        @client.event
        async def on_disconnect() -> None:  # noqa: WPS430
            manager.set_gateway_ready(account_id, False)

        start_task = asyncio.create_task(
            client.start(token),
            name=f"discord-selfcord-start-{account_id[:8]}",
        )
        stop_task = asyncio.create_task(stop_event.wait())
        try:
            done, pending = await asyncio.wait(
                {start_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            if stop_task in done or stop_event.is_set():
                break
            # start_task finished unexpectedly — reconnect with backoff
            exc = None
            if start_task in done and not start_task.cancelled():
                try:
                    start_task.result()
                except Exception as err:
                    exc = err
            if stop_event.is_set():
                break
            logger.warning(
                "discord selfcord reconnect account=%s err=%s proxy=%s backoff=%.1fs",
                account_id[:8],
                exc or "closed",
                "yes" if proxy_url else "direct",
                backoff_sec,
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff_sec)
                break
            except asyncio.TimeoutError:
                backoff_sec = min(backoff_sec * 2, 60.0)
        except asyncio.CancelledError:
            raise
        finally:
            manager.set_gateway_ready(account_id, False)
            manager.unregister_discord_library_client(account_id, client)
            try:
                await client.close()
            except Exception:
                logger.debug(
                    "discord selfcord close failed account=%s",
                    account_id[:8],
                    exc_info=True,
                )

    manager.set_gateway_ready(account_id, False)
    logger.info("discord selfcord stopped account=%s", account_id[:8])


async def _emit_message_event(
    account_id: str,
    manager: DiscordClientManager,
    client: Any,
    message: Any,
) -> None:
    channel = getattr(message, "channel", None)
    channel_id = str(getattr(channel, "id", "") or "").strip()
    message_id = str(getattr(message, "id", "") or "").strip()
    content = str(getattr(message, "content", "") or "")
    if not channel_id or not message_id:
        return

    author = getattr(message, "author", None)
    author_id = str(getattr(author, "id", "") or "").strip()
    self_user = getattr(client, "user", None)
    self_user_id = str(getattr(self_user, "id", "") or "").strip()
    account_client = manager.client_for_account(account_id)
    if account_client is not None and account_client.user_id:
        self_user_id = account_client.user_id or self_user_id

    is_incoming = bool(author_id) and author_id != self_user_id
    guild = getattr(message, "guild", None)
    guild_id = str(getattr(guild, "id", "") or "").strip()
    is_group = bool(guild_id)

    title = channel_id
    channel_meta = manager.channel_meta(account_id, channel_id)
    if channel_meta:
        title = str(channel_meta.get("title") or title)
        is_group = bool(channel_meta.get("is_group", is_group))
    elif guild is not None:
        name = str(getattr(channel, "name", "") or "").strip()
        title = f"#{name}" if name else title
        is_group = True
    else:
        title = _author_display_name(author) or title
        channel_type_raw = getattr(channel, "type", 0)
        channel_type = int(getattr(channel_type_raw, "value", channel_type_raw) or 0)
        is_group = channel_type == 3

    from_name = _author_display_name(author) or None
    metadata: dict[str, Any] = {}
    if from_name:
        metadata["from_name"] = from_name
    sent_at = _message_sent_at(message)

    if is_incoming:
        await manager.event_sink.on_incoming(
            IncomingMessageEvent(
                connection_id=account_id,
                provider="discord",
                external_chat_id=channel_id,
                external_message_id=message_id,
                from_id=author_id or "unknown",
                text=content,
                sent_at=sent_at,
                title=title,
                is_group=is_group,
                metadata=metadata,
            )
        )
    else:
        await manager.event_sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="discord",
                external_chat_id=channel_id,
                external_message_id=message_id,
                text=content,
                from_id=author_id or self_user_id or account_id,
                sent_at=sent_at,
                title=title,
                is_group=is_group,
                metadata={"emit_ws": True},
            )
        )


async def _handle_raw_gateway_event(
    account_id: str,
    manager: DiscordClientManager,
    payload: Any,
) -> None:
    """Track voice presence; VoiceClient owns join/leave/audio transport."""
    try:
        if isinstance(payload, (bytes, bytearray)):
            message = json.loads(payload.decode("utf-8"))
        elif isinstance(payload, str):
            message = json.loads(payload)
        elif isinstance(payload, dict):
            message = payload
        else:
            return
    except Exception:
        return

    if not isinstance(message, dict) or message.get("op") != 0:
        return
    event = str(message.get("t") or "")
    data = message.get("d") or {}
    if not isinstance(data, dict):
        return

    if event == "VOICE_SERVER_UPDATE":
        # Observability only — discord.py-self VoiceClient consumes this event.
        endpoint = str(data.get("endpoint") or "").strip()
        voice_token = str(data.get("token") or "").strip()
        guild_id = str(data.get("guild_id") or "").strip()
        current = manager.voice_session(account_id)
        if str(current.get("state") or "") in {"joining", "connected", "reconnecting"}:
            manager.update_voice_session(
                account_id,
                endpoint=endpoint,
                token=voice_token,
                guild_id=guild_id or current.get("guild_id"),
            )
        return

    if event == "VOICE_STATE_UPDATE":
        manager.apply_voice_state_update(account_id, data)
        user_id = str(data.get("user_id") or "").strip()
        client = manager.client_for_account(account_id)
        if client is None or not user_id or user_id != client.user_id:
            return
        channel_id = data.get("channel_id")
        guild_id = str(data.get("guild_id") or "").strip()
        session_id = str(data.get("session_id") or "").strip()
        if channel_id in (None, ""):
            current = manager.voice_session(account_id)
            current_state = str(current.get("state") or "")
            if current_state in {"joining", "reconnecting"}:
                logger.info(
                    "discord ignore self-leave during %s account=%s",
                    current_state,
                    account_id[:8],
                )
            else:
                manager.clear_voice_session(account_id)
        else:
            current_state = str(manager.voice_session(account_id).get("state") or "")
            manager.update_voice_session(
                account_id,
                state="connected" if current_state == "connected" else "joining",
                channel_id=str(channel_id),
                guild_id=guild_id,
                session_id=session_id,
            )
