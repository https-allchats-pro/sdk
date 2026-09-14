"""VK provider — multi-account runtime.

Public name: ``VKProvider``. Legacy alias: ``VkClientManager``.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from allchats_sdk.providers.vk.client import (
    VkApiError,
    build_oauth_url,
    exchange_vk_id_token,
    extract_user_nickname,
    generate_code_challenge,
    generate_code_verifier,
    get_user_info,
    get_vk_id_user_info,
    peer_id_from_external_chat_id,
    refresh_vk_id_token,
    send_message,
    token_expires_at_ms,
)
from allchats_sdk.providers.vk.native_api import (
    VK_REACTION_EMOJI_TO_ID,
    delete_messages_async,
    delete_reaction_async,
    extract_user_avatar_url,
    get_conversation_message_id_async,
    send_reaction_async,
)
from allchats_sdk.providers.common.proxy import requests_proxies_from_credentials
from allchats_sdk.providers.vk.longpoll_worker import run_vk_longpoll_worker
from allchats_sdk.providers.credentials_cache import CredentialsCache
from allchats_sdk.config import Settings
from allchats_sdk.events import (
    ChatsDiscoveredEvent,
    CredentialsUpdatedEvent,
    OutgoingMessageEvent,
)
from allchats_sdk.protocols import DeliveryTracker, EventSink, IncomingMessageHandler
from allchats_sdk.credentials import merge_credentials, vk_authorized
from allchats_sdk.errors import ValidationError
from allchats_sdk.internal.observability import record_auth

logger = logging.getLogger(__name__)

VK_NOT_CONFIGURED = "vk app_id, app_secret and redirect_uri are not configured"


@dataclass
class VkAccountClient:
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


class VKProvider:
    provider_id = "vk"

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
        self._delivery_tracker: DeliveryTracker | None = None
        self._clients: dict[str, VkAccountClient] = {}
        self._longpoll_tasks: dict[str, asyncio.Task[None]] = {}
        self._oauth_pkce: dict[str, str] = {}
        self._oauth_states: dict[str, str] = {}
        self._login_tasks: dict[str, asyncio.Task[None]] = {}
        self._twofactor_queues: dict[str, asyncio.Queue[tuple[str, bool]]] = {}
        self._captcha_queues: dict[str, asyncio.Queue[str]] = {}
        self._captcha_images: dict[str, bytes] = {}
        self._verification_hints: dict[str, str] = {}
        self._login_modes: dict[str, str] = {}
        self._qr_tasks: dict[str, asyncio.Task[None]] = {}

    def is_configured(self) -> bool:
        return self._settings.vk.is_configured()

    def requests_proxies(self, credentials: dict[str, Any]) -> dict[str, str] | None:
        return requests_proxies_from_credentials(credentials)

    @property
    def event_sink(self) -> EventSink:
        return self._sink

    async def account_credentials(self, account_id: str) -> dict[str, Any]:
        return self._creds.get_or_empty(account_id)

    def login_auth_configured(self) -> bool:
        return self._settings.vk.login_auth_configured()

    def captcha_image_for_account(self, account_id: str) -> bytes | None:
        return self._captcha_images.get(account_id)

    def verification_hint_for_account(self, account_id: str) -> str:
        return self._verification_hints.get(account_id, "")

    def is_login_auth_active(self, account_id: str) -> bool:
        task = self._login_tasks.get(account_id)
        return task is not None and not task.done()

    def is_qr_auth_active(self, account_id: str) -> bool:
        task = self._qr_tasks.get(account_id)
        return task is not None and not task.done()

    def resolve_oauth_account_id(self, state: str) -> str:
        raw_state = state.strip()
        account_id = self._oauth_states.pop(raw_state, "").strip()
        if account_id:
            return account_id
        return raw_state

    def oauth_redirect_uri(self) -> str:
        return self._settings.vk.redirect_uri.strip()

    def oauth_app_id(self) -> str:
        return self._settings.vk.app_id.strip()

    def oauth_app_secret(self) -> str:
        return self._settings.vk.app_secret.strip()

    def oauth_scopes(self) -> str:
        return self._settings.vk.scopes.strip()

    def client_for_account(self, account_id: str) -> VkAccountClient | None:
        return self._clients.get(account_id)

    def connected_count(self) -> int:
        return len(self._clients)

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
    ) -> VkAccountClient:
        client = self._clients.get(account_id)
        if client is None:
            client = VkAccountClient(account_id=account_id)
            self._clients[account_id] = client
        client.state_instance = state_instance
        client.user_id = user_id
        client.error = error
        client.running = running
        return client

    def build_oauth_authorization_url(self, account_id: str) -> str:
        client_id = self.oauth_app_id()
        redirect_uri = self.oauth_redirect_uri()
        service_token = self.oauth_app_secret()
        if not client_id or not redirect_uri or not service_token:
            raise ValidationError("vk app_id, app_secret and redirect_uri are required")

        oauth_state = secrets.token_urlsafe(32)
        self._oauth_states[oauth_state] = account_id
        code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(code_verifier)
        self._oauth_pkce[account_id] = code_verifier

        return build_oauth_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=oauth_state,
            scopes=self.oauth_scopes(),
            code_challenge=code_challenge,
        )

    async def connect_with_token(
        self,
        account_id: str,
        *,
        access_token: str,
        auth_method: str = "token",
    ) -> dict[str, Any]:
        access_token = access_token.strip()
        if not access_token:
            raise ValidationError("access_token is required")

        return await self._persist_credentials(
            account_id,
            access_token=access_token,
            auth_method=auth_method,
        )

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
        if not self.login_auth_configured():
            raise ValidationError("vk app_id is not configured")

        try:
            app_id = int(self.oauth_app_id())
        except ValueError as exc:
            raise ValidationError("vk app_id must be numeric for login/password auth") from exc

        await self.cancel_login_auth(account_id)
        self._login_modes[account_id] = "password"
        self.set_client_state(account_id, state_instance="starting", running=True)
        from allchats_sdk.providers.vk.login_auth_worker import run_vk_login_auth_worker

        credentials = await self.account_credentials(account_id)
        proxies = self.requests_proxies(credentials)

        self._login_tasks[account_id] = asyncio.create_task(
            run_vk_login_auth_worker(
                account_id,
                login=login,
                password=password,
                app_id=app_id,
                manager=self,
                sms_mode=False,
                proxies=proxies,
            ),
            name=f"vk-login-{account_id[:8]}",
        )

    async def start_sms_auth(
        self,
        account_id: str,
        *,
        phone: str,
    ) -> None:
        phone = phone.strip()
        if not phone:
            raise ValidationError("phone is required")
        if not self.login_auth_configured():
            raise ValidationError("vk app_id is not configured")

        try:
            app_id = int(self.oauth_app_id())
        except ValueError as exc:
            raise ValidationError("vk app_id must be numeric for sms auth") from exc

        await self.cancel_login_auth(account_id)
        self._login_modes[account_id] = "sms"
        self._verification_hints[account_id] = phone
        self._twofactor_queues.setdefault(account_id, asyncio.Queue())
        self.set_client_state(account_id, state_instance="smsRequired", running=True)
        from allchats_sdk.providers.vk.login_auth_worker import run_vk_login_auth_worker

        credentials = await self.account_credentials(account_id)
        proxies = self.requests_proxies(credentials)

        self._login_tasks[account_id] = asyncio.create_task(
            run_vk_login_auth_worker(
                account_id,
                login=phone,
                password="",
                app_id=app_id,
                manager=self,
                sms_mode=True,
                proxies=proxies,
            ),
            name=f"vk-sms-{account_id[:8]}",
        )

    async def wait_verification_code(
        self,
        account_id: str,
        *,
        kind: str,
        hint: str = "",
    ) -> tuple[str, bool]:
        if kind in {"sms", "security"}:
            state_instance = "smsRequired"
        else:
            state_instance = "passwordRequired"
        if hint:
            self._verification_hints[account_id] = hint
        self.set_client_state(account_id, state_instance=state_instance, running=True)
        queue = self._twofactor_queues.setdefault(account_id, asyncio.Queue())
        return await asyncio.wait_for(queue.get(), timeout=300.0)

    async def wait_2fa_code(self, account_id: str) -> tuple[str, bool]:
        return await self.wait_verification_code(account_id, kind="twofactor")

    async def wait_captcha_key(self, account_id: str, captcha: Any) -> str:
        def _fetch_image() -> bytes:
            return captcha.get_image()

        try:
            image_bytes = await asyncio.to_thread(_fetch_image)
            self._captcha_images[account_id] = image_bytes
        except Exception as exc:
            logger.warning(
                "failed to fetch vk captcha image account=%s: %s",
                account_id[:8],
                exc,
            )

        self.set_client_state(account_id, state_instance="captchaRequired", running=True)
        queue = self._captcha_queues.setdefault(account_id, asyncio.Queue())
        return await asyncio.wait_for(queue.get(), timeout=300.0)

    async def submit_2fa_code(
        self,
        account_id: str,
        *,
        code: str,
        remember_device: bool = False,
    ) -> None:
        raw_code = code.strip()
        if not raw_code:
            raise ValidationError("code is required")
        queue = self._twofactor_queues.get(account_id)
        if queue is None:
            raise ValidationError("verification code is not required")
        await queue.put((raw_code, remember_device))

    async def submit_captcha(self, account_id: str, *, key: str) -> None:
        raw_key = key.strip()
        if not raw_key:
            raise ValidationError("captcha key is required")
        queue = self._captcha_queues.get(account_id)
        if queue is None:
            raise ValidationError("captcha is not required")
        await queue.put(raw_key)

    def cleanup_login_auth(self, account_id: str) -> None:
        self._twofactor_queues.pop(account_id, None)
        self._captcha_queues.pop(account_id, None)
        self._captcha_images.pop(account_id, None)
        self._verification_hints.pop(account_id, None)
        self._login_modes.pop(account_id, None)
        self._login_tasks.pop(account_id, None)

    async def start_qr(
        self,
        account_id: str,
        credentials: dict[str, Any] | None = None,
        *,
        refresh: bool = False,
    ) -> VkAccountClient:
        _ = credentials  # conceptual API parity with TelegramProvider
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

        from allchats_sdk.providers.vk.qr_auth_worker import run_vk_qr_auth_worker

        credentials = await self.account_credentials(account_id)
        proxies = self.requests_proxies(credentials)

        task = asyncio.create_task(
            run_vk_qr_auth_worker(
                account_id,
                manager=self,
                client=client,
                proxies=proxies,
            ),
            name=f"vk-qr-{account_id[:8]}",
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
                raise ValidationError(client.error or "vk qr auth failed")
            await asyncio.sleep(0.25)

        if client.error:
            raise ValidationError(client.error)
        raise ValidationError("qr not available: vk did not respond in time")

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
                logger.warning("vk qr auth cancel failed account=%s: %s", account_id[:8], exc)
        self.cleanup_qr_auth(account_id)

    @staticmethod
    def to_qr_response(client: VkAccountClient) -> dict[str, Any]:
        return {
            "type": "qrCode",
            "qr_link": client.auth_url,
            "polling_interval": 2,
            "qr_status": client.qr_status,
        }

    async def cancel_login_auth(self, account_id: str) -> None:
        task = self._login_tasks.pop(account_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("vk login auth cancel failed account=%s: %s", account_id[:8], exc)
        self.cleanup_login_auth(account_id)

    async def connect_with_oauth_code(
        self,
        account_id: str,
        *,
        code: str,
        oauth_state: str,
        device_id: str = "",
    ) -> dict[str, Any]:
        if not self.is_configured():
            raise ValidationError(VK_NOT_CONFIGURED)

        redirect_uri = self.oauth_redirect_uri()
        if not redirect_uri:
            raise ValidationError("vk redirect_uri is not configured")

        code_verifier = self._oauth_pkce.pop(account_id, "").strip()
        if not code_verifier:
            raise ValidationError("vk oauth session expired, restart authorization")
        if not device_id.strip():
            raise ValidationError("device_id is required for vk id oauth")

        credentials = await self.account_credentials(account_id)
        proxies = self.requests_proxies(credentials)

        token_response = await exchange_vk_id_token(
            client_id=self.oauth_app_id(),
            service_token=self.oauth_app_secret(),
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            device_id=device_id.strip(),
            state=oauth_state,
            proxies=proxies,
        )

        access_token = str(token_response.get("access_token") or "").strip()
        if not access_token:
            raise ValidationError("vk token response missing access_token")

        return await self._persist_credentials(
            account_id,
            access_token=access_token,
            auth_method="oauth",
            token_response=token_response,
            device_id=device_id,
        )

    async def ensure_valid_token(self, account_id: str, credentials: dict[str, Any]) -> dict[str, Any]:
        if not vk_authorized(credentials):
            raise ValidationError("account is not authorized")

        auth_method = str(credentials.get("auth_method") or "").strip()
        if auth_method != "oauth":
            return credentials

        expires_at = int(credentials.get("token_expires_at") or 0)
        now_ms = int(time.time() * 1000)
        if credentials.get("access_token") and expires_at > now_ms + 60_000:
            return credentials

        refresh_token = str(credentials.get("refresh_token") or "").strip()
        device_id = str(credentials.get("vk_device_id") or "").strip()
        if not refresh_token or not device_id:
            return credentials

        try:
            token_response = await refresh_vk_id_token(
                client_id=self.oauth_app_id(),
                service_token=self.oauth_app_secret(),
                refresh_token=refresh_token,
                device_id=device_id,
                state=account_id,
                proxies=self.requests_proxies(credentials),
            )
        except VkApiError as exc:
            logger.warning("vk token refresh failed account=%s: %s", account_id[:8], exc)
            return credentials

        access_token = str(token_response.get("access_token") or "").strip()
        if not access_token:
            return credentials

        existing = self._creds.get_or_empty(account_id) or credentials
        incoming: dict[str, Any] = {
            "access_token": access_token,
            "refresh_token": str(token_response.get("refresh_token") or refresh_token),
            "token_expires_at": token_expires_at_ms(token_response),
            "user_id": str(token_response.get("user_id") or existing.get("user_id") or ""),
            "vk_device_id": device_id or str(existing.get("vk_device_id") or ""),
        }
        merged = merge_credentials(existing, incoming)
        self._creds.set(account_id, merged)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="vk",
                credentials=merged,
                user_id=str(merged.get("user_id") or ""),
            )
        )
        return merged

    async def _persist_credentials(
        self,
        account_id: str,
        *,
        access_token: str,
        auth_method: str,
        token_response: dict[str, Any] | None = None,
        device_id: str = "",
    ) -> dict[str, Any]:
        client_id = self.oauth_app_id()
        existing = self._creds.get_or_empty(account_id) or {"device_id": account_id}
        proxies = self.requests_proxies(existing)

        user_info: dict[str, Any] | None = None
        resolved_user_id = str((token_response or {}).get("user_id") or "").strip()

        try:
            user_info = await get_user_info(access_token=access_token, proxies=proxies)
        except VkApiError:
            try:
                user_info = await get_vk_id_user_info(
                    access_token=access_token,
                    client_id=client_id,
                    proxies=proxies,
                )
            except VkApiError as exc:
                if not resolved_user_id:
                    raise ValidationError(f"failed to verify vk token: {exc}") from exc

        if user_info:
            resolved_user_id = str(user_info.get("id") or user_info.get("user_id") or resolved_user_id).strip()
        if not resolved_user_id:
            raise ValidationError("failed to resolve vk user id")

        nickname = extract_user_nickname(user_info or {"user_id": resolved_user_id})
        avatar_url = extract_user_avatar_url(user_info) if user_info else None

        incoming: dict[str, Any] = {
            "auth_method": auth_method,
            "access_token": access_token,
            "user_id": resolved_user_id,
            "device_id": str(existing.get("device_id") or account_id),
            "state_instance": "authorized",
        }
        if avatar_url:
            incoming["avatar_url"] = avatar_url
        if device_id.strip():
            incoming["vk_device_id"] = device_id.strip()
        if token_response:
            refresh_token = str(token_response.get("refresh_token") or "").strip()
            if refresh_token:
                incoming["refresh_token"] = refresh_token
            if token_response.get("expires_in") is not None:
                incoming["token_expires_at"] = token_expires_at_ms(token_response)

        merged = merge_credentials(existing, incoming)
        self._creds.set(account_id, merged)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="vk",
                credentials=merged,
                user_id=resolved_user_id,
                nickname=nickname,
            )
        )
        await self.ensure_longpoll(account_id, merged)
        record_auth("vk", "success")
        return merged

    async def ensure_longpoll(
        self,
        account_id: str,
        credentials: dict[str, Any] | None = None,
    ) -> VkAccountClient:
        if credentials is None:
            credentials = self._creds.get_or_empty(account_id)

        credentials = await self.ensure_valid_token(account_id, credentials or {})
        self._creds.set(account_id, credentials)

        if not vk_authorized(credentials):
            return self.set_client_state(
                account_id,
                state_instance="notAuthorized",
                running=False,
            )

        existing_task = self._longpoll_tasks.get(account_id)
        if existing_task is not None and not existing_task.done():
            return self.set_client_state(
                account_id,
                state_instance="authorized",
                user_id=str(credentials.get("user_id") or ""),
                running=True,
            )

        await self.stop_longpoll(account_id)

        user_id = str(credentials.get("user_id") or "").strip()
        client = self.set_client_state(
            account_id,
            state_instance="authorized",
            user_id=user_id,
            running=True,
        )
        client.stop_event = asyncio.Event()

        access_token = str(credentials.get("access_token") or "").strip()
        proxies = self.requests_proxies(credentials)

        try:
            await self._sink.on_chats_discovered(
                ChatsDiscoveredEvent(
                    connection_id=account_id,
                    provider="vk",
                    runtime={"access_token": access_token, "proxies": proxies},
                )
            )
        except Exception:
            logger.exception("vk initial chat sync failed account=%s", account_id[:8])

        self._longpoll_tasks[account_id] = asyncio.create_task(
            run_vk_longpoll_worker(
                account_id,
                access_token=access_token,
                owner_user_id=user_id,
                event_sink=self._sink,
                incoming_handler=self._incoming_handler,
                stop_event=client.stop_event,
                proxies=proxies,
                delivery_tracker=getattr(self, "_delivery_tracker", None),
            ),
            name=f"vk-longpoll-{account_id[:8]}",
        )
        return client

    async def stop_longpoll(self, account_id: str) -> None:
        client = self._clients.get(account_id)
        if client is not None:
            client.stop_event.set()
            client.running = False

        task = self._longpoll_tasks.pop(account_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("vk longpoll task cleanup failed account=%s: %s", account_id[:8], exc)

        self._oauth_pkce.pop(account_id, None)
        self._oauth_states = {
            state: mapped_account_id
            for state, mapped_account_id in self._oauth_states.items()
            if mapped_account_id != account_id
        }

    async def disconnect(self, account_id: str) -> None:
        await self.cancel_login_auth(account_id)
        await self.stop_qr(account_id)
        await self.stop_longpoll(account_id)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="vk",
                credentials={},
                clear=True,
            )
        )
        self._creds.pop(account_id)
        self.unregister_client(account_id)

    async def connect_account(
        self,
        account_id: str,
        credentials: dict[str, Any],
    ) -> VkAccountClient:
        if not vk_authorized(credentials):
            raise ValidationError("account is not authorized")
        self._creds.set(account_id, credentials)
        return await self.ensure_longpoll(account_id, credentials)

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

        credentials = await self.ensure_valid_token(account_id, self._creds.get(account_id))
        if not vk_authorized(credentials):
            raise ValidationError("vk account is not authorized")

        access_token = str(credentials.get("access_token") or "").strip()
        external_chat_id = chat_id.strip()
        reply_to = None
        if reply_to_external_id:
            try:
                reply_to = int(str(reply_to_external_id).strip())
            except ValueError as exc:
                raise ValidationError("reply_to_external_id must be numeric for vk") from exc
        try:
            peer_id = peer_id_from_external_chat_id(external_chat_id)
            message_id_num = await send_message(
                access_token=access_token,
                peer_id=peer_id,
                text=trimmed,
                reply_to=reply_to,
                proxies=self.requests_proxies(credentials),
            )
        except (VkApiError, ValueError) as exc:
            raise ValidationError(f"failed to send vk message: {exc}") from exc

        message_id = str(message_id_num)
        from_id = str(credentials.get("user_id") or account_id)

        await self._sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="vk",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                text=trimmed,
                from_id=from_id,
                sent_at=datetime.now(UTC),
                metadata={"emit_ws": False},
            )
        )
        return message_id, external_chat_id

    async def _resolve_cmid(
        self,
        *,
        access_token: str,
        external_message_id: str,
        external_meta: dict[str, Any] | None,
        proxies: dict[str, str] | None,
    ) -> int:
        if external_meta and external_meta.get("cmid") is not None:
            try:
                return int(external_meta["cmid"])
            except (TypeError, ValueError):
                pass
        try:
            message_id = int(str(external_message_id).strip())
        except ValueError as exc:
            raise ValidationError("external_message_id must be numeric for vk") from exc
        cmid = await get_conversation_message_id_async(
            access_token=access_token,
            message_id=message_id,
            proxies=proxies,
        )
        if cmid is None:
            raise ValidationError("failed to resolve vk conversation_message_id")
        return cmid

    async def add_reaction(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
        emoji: str,
        external_meta: dict[str, Any] | None = None,
    ) -> None:
        reaction_id = VK_REACTION_EMOJI_TO_ID.get(emoji)
        if reaction_id is None:
            raise ValidationError(f"unsupported vk reaction emoji: {emoji}")

        credentials = await self.ensure_valid_token(account_id, self._creds.get(account_id))
        access_token = str(credentials.get("access_token") or "").strip()
        external_chat_id = chat_id.strip()
        peer_id = peer_id_from_external_chat_id(external_chat_id)
        proxies = self.requests_proxies(credentials)
        cmid = await self._resolve_cmid(
            access_token=access_token,
            external_message_id=external_message_id,
            external_meta=external_meta,
            proxies=proxies,
        )
        try:
            await send_reaction_async(
                access_token=access_token,
                peer_id=peer_id,
                cmid=cmid,
                reaction_id=reaction_id,
                proxies=proxies,
            )
        except Exception as exc:
            raise ValidationError(f"failed to send vk reaction: {exc}") from exc

    async def remove_reaction(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
        external_meta: dict[str, Any] | None = None,
    ) -> None:
        credentials = await self.ensure_valid_token(account_id, self._creds.get(account_id))
        access_token = str(credentials.get("access_token") or "").strip()
        external_chat_id = chat_id.strip()
        peer_id = peer_id_from_external_chat_id(external_chat_id)
        proxies = self.requests_proxies(credentials)
        cmid = await self._resolve_cmid(
            access_token=access_token,
            external_message_id=external_message_id,
            external_meta=external_meta,
            proxies=proxies,
        )
        try:
            await delete_reaction_async(
                access_token=access_token,
                peer_id=peer_id,
                cmid=cmid,
                proxies=proxies,
            )
        except Exception as exc:
            raise ValidationError(f"failed to remove vk reaction: {exc}") from exc

    async def forward_message(
        self,
        account_id: str,
        *,
        source_chat_id: str,
        external_message_id: str,
        target_chat_id: str,
        text: str = "",
    ) -> tuple[str, str]:
        credentials = await self.ensure_valid_token(account_id, self._creds.get(account_id))
        access_token = str(credentials.get("access_token") or "").strip()
        target_external = target_chat_id.strip()
        peer_id = peer_id_from_external_chat_id(target_external)
        try:
            message_id_num = await send_message(
                access_token=access_token,
                peer_id=peer_id,
                text=text or "",
                forward_messages=str(external_message_id).strip(),
                proxies=self.requests_proxies(credentials),
            )
        except (VkApiError, ValueError) as exc:
            raise ValidationError(f"failed to forward vk message: {exc}") from exc

        message_id = str(message_id_num)
        from_id = str(credentials.get("user_id") or account_id)
        await self._sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="vk",
                external_chat_id=target_external,
                external_message_id=message_id,
                text=text or "",
                from_id=from_id,
                sent_at=datetime.now(UTC),
                metadata={"emit_ws": False},
            )
        )
        return message_id, target_external

    async def delete_message(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
    ) -> None:
        credentials = await self.ensure_valid_token(account_id, self._creds.get(account_id))
        access_token = str(credentials.get("access_token") or "").strip()
        external_chat_id = chat_id.strip()
        peer_id = peer_id_from_external_chat_id(external_chat_id)
        try:
            msg_id = int(str(external_message_id).strip())
        except ValueError as exc:
            raise ValidationError("external_message_id must be numeric for vk") from exc
        try:
            await delete_messages_async(
                access_token=access_token,
                message_ids=[msg_id],
                peer_id=peer_id,
                delete_for_all=True,
                proxies=self.requests_proxies(credentials),
            )
        except Exception as exc:
            raise ValidationError(f"failed to delete vk message: {exc}") from exc

VkClientManager = VKProvider

__all__ = [
    "VKProvider",
    "VkAccountClient",
    "VkClientManager",
]
