from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime
from dataclasses import dataclass, field
from typing import Any

from allchats_sdk.providers.telegram.entities import (
    ensure_entity_cache,
    resolve_send_entity,
)
from allchats_sdk.providers.telegram.proxy import resolve_telegram_proxy
from allchats_sdk.providers.telegram.qr_worker import (
    run_telegram_qr_worker,
    telegram_connect_timeout,
    telegram_qr_wait_timeout,
)
from allchats_sdk.providers.telegram.session_worker import run_telegram_session_worker
from allchats_sdk.providers.credentials_cache import CredentialsCache
from allchats_sdk.config import Settings
from allchats_sdk.events import CredentialsUpdatedEvent, OutgoingMessageEvent
from allchats_sdk.protocols import (
    DeliveryTracker,
    EventSink,
    IncomingMessageHandler,
    MediaStorage,
)
from allchats_sdk.providers.telegram.entities import describe_peer, entity_avatar_url
from allchats_sdk.credentials import telegram_authorized
from allchats_sdk.errors import MessengerClientUnavailableError, ValidationError

logger = logging.getLogger(__name__)

TELEGRAM_NOT_CONFIGURED = "telegram app_id and app_hash are not configured"

# Telegram default reactions use specific codepoints (no FE0F, 😁 instead of 😂, etc.).
_TELEGRAM_REACTION_ALIASES: dict[str, str] = {
    "❤️": "❤",
    "❤︎": "❤",
    "😂": "😁",
    "🤣": "😁",
    "😮": "😱",
    "👍🏻": "👍",
    "👍🏼": "👍",
    "👍🏽": "👍",
    "👍🏾": "👍",
    "👍🏿": "👍",
}


def _normalize_telegram_reaction_emoji(emoji: str) -> str:
    raw = str(emoji or "").strip()
    if not raw:
        raise ValidationError("emoji is required")
    if raw in _TELEGRAM_REACTION_ALIASES:
        return _TELEGRAM_REACTION_ALIASES[raw]
    # Strip emoji presentation selector; Telegram expects plain codepoints for many reactions.
    normalized = raw.replace("\ufe0f", "")
    return _TELEGRAM_REACTION_ALIASES.get(normalized, normalized)


@dataclass
class TelegramAccountClient:
    account_id: str
    state_instance: str = "starting"
    user_id: str = ""
    error: str = ""
    running: bool = False
    qr_link: str = ""
    track_id: str = ""
    polling_interval: int = 3000
    expires_at: int = 0
    password_hint: str = ""
    telethon_client: Any = field(default=None, repr=False, compare=False)
    entities_loaded: bool = False

    @property
    def is_authorized(self) -> bool:
        return self.state_instance == "authorized" or bool(str(self.user_id or "").strip())


class TelegramClientManager:
    provider_id = "telegram"

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
        self._media_storage: MediaStorage | None = None
        self._clients: dict[str, TelegramAccountClient] = {}
        self._qr_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_tasks: dict[str, asyncio.Task[None]] = {}
        self._password_queues: dict[str, asyncio.Queue[str]] = {}

    @property
    def event_sink(self) -> EventSink:
        return self._sink

    def is_configured(self) -> bool:
        telegram = self._settings.telegram
        return bool(telegram.app_id) and bool(str(telegram.app_hash or "").strip())

    def client_for_account(self, account_id: str) -> TelegramAccountClient | None:
        return self._clients.get(account_id)

    def connected_count(self) -> int:
        return len(self._clients)

    def register_client(self, client: TelegramAccountClient) -> None:
        self._clients[client.account_id] = client

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
        password_hint: str | None = None,
    ) -> TelegramAccountClient:
        client = self._clients.get(account_id)
        if client is None:
            client = TelegramAccountClient(account_id=account_id)
            self._clients[account_id] = client
        client.state_instance = state_instance
        client.user_id = user_id
        client.error = error
        client.running = running
        if password_hint is not None:
            client.password_hint = password_hint
        elif state_instance != "passwordRequired":
            client.password_hint = ""
        if state_instance == "passwordRequired":
            self._password_queues.setdefault(account_id, asyncio.Queue())
        return client

    def update_qr_state(
        self,
        account_id: str,
        *,
        qr_link: str,
        track_id: str,
        polling_interval: int,
        expires_at: int,
        state_instance: str = "starting",
    ) -> TelegramAccountClient:
        client = self.set_client_state(account_id, state_instance=state_instance, running=True)
        client.qr_link = qr_link
        client.track_id = track_id
        client.polling_interval = polling_interval
        client.expires_at = expires_at
        client.error = ""
        return client

    def find_active_qr(self, account_id: str) -> TelegramAccountClient | None:
        client = self._clients.get(account_id)
        if client is None:
            return None
        if not client.qr_link or not client.track_id:
            return None
        if client.expires_at and client.expires_at <= int(time.time() * 1000):
            return None
        if client.state_instance in {"error", "authorized"}:
            return None
        return client

    def is_qr_login_active(self, account_id: str) -> bool:
        return self.find_active_qr(account_id) is not None

    def is_account_busy(self, account_id: str) -> bool:
        client = self._clients.get(account_id)
        if client is None or not client.running:
            return False
        return client.state_instance not in {"error", "stopped"}

    @staticmethod
    def _is_session_ready(client: TelegramAccountClient | None) -> bool:
        return (
            client is not None
            and client.running
            and client.state_instance == "authorized"
            and client.is_authorized
            and client.telethon_client is not None
        )

    def _session_wait_timeout(self, credentials: dict[str, Any]) -> float:
        proxy = resolve_telegram_proxy(settings=self._settings, credentials=credentials)
        return telegram_connect_timeout(proxy) + 20.0

    async def ensure_account_worker(self, account_id: str, credentials: dict[str, Any]) -> TelegramAccountClient:
        if not self.is_configured():
            raise ValidationError(TELEGRAM_NOT_CONFIGURED)

        if not telegram_authorized(credentials):
            return self.set_client_state(
                account_id,
                state_instance="notAuthorized",
                running=False,
            )

        self._creds.set(account_id, credentials)
        existing = self.client_for_account(account_id)
        if self._is_session_ready(existing):
            return existing

        return await self._start_session_worker(account_id, credentials, wait=False)

    async def connect_account(
        self,
        account_id: str,
        credentials: dict[str, Any],
    ) -> TelegramAccountClient:
        if not self.is_configured():
            raise ValidationError(TELEGRAM_NOT_CONFIGURED)
        if not telegram_authorized(credentials):
            raise ValidationError("account is not authorized")

        self._creds.set(account_id, credentials)
        existing = self.client_for_account(account_id)
        if self._is_session_ready(existing):
            return existing

        if existing is not None and existing.running and existing.state_instance == "starting":
            return await self._wait_client_authorized(account_id, credentials)

        return await self._start_session_worker(account_id, credentials, wait=True)

    async def _wait_client_authorized(
        self,
        account_id: str,
        credentials: dict[str, Any] | None = None,
        *,
        timeout_sec: float | None = None,
    ) -> TelegramAccountClient:
        if timeout_sec is None:
            timeout_sec = (
                self._session_wait_timeout(credentials or {})
                if credentials is not None
                else 65.0
            )
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            client = self.client_for_account(account_id)
            if self._is_session_ready(client):
                return client
            if client is None:
                break
            if client.state_instance == "error":
                raise MessengerClientUnavailableError(client.error or "connect failed")
            if client.state_instance == "notAuthorized":
                raise ValidationError("account is not authorized")
            await asyncio.sleep(0.25)

        raise MessengerClientUnavailableError("connect timeout")

    async def _start_session_worker(
        self,
        account_id: str,
        credentials: dict[str, Any],
        *,
        wait: bool,
    ) -> TelegramAccountClient:
        await self.stop_qr(account_id)
        await self.stop_session(account_id)

        client = TelegramAccountClient(account_id=account_id, state_instance="starting", running=True)
        self._clients[account_id] = client

        task = asyncio.create_task(
            run_telegram_session_worker(
                settings=self._settings,
                account_id=account_id,
                credentials=credentials,
                client_state=client,
                manager=self,
                event_sink=self._sink,
                incoming_handler=self._incoming_handler,
            ),
            name=f"telegram-session-{account_id[:8]}",
        )
        self._session_tasks[account_id] = task
        task.add_done_callback(lambda _task: self._session_tasks.pop(account_id, None))

        if not wait:
            return client

        deadline = time.time() + self._session_wait_timeout(credentials)
        while time.time() < deadline:
            if self._is_session_ready(client):
                return client
            if client.state_instance == "error":
                raise MessengerClientUnavailableError(client.error or "connect failed")
            if client.state_instance == "notAuthorized":
                raise ValidationError("account is not authorized")
            await asyncio.sleep(0.25)

        raise MessengerClientUnavailableError("connect timeout")

    async def start_qr(
        self,
        account_id: str,
        credentials: dict[str, Any],
        *,
        refresh: bool = False,
    ) -> TelegramAccountClient:
        if not self.is_configured():
            raise ValidationError(TELEGRAM_NOT_CONFIGURED)

        self._creds.set(account_id, credentials)

        if not refresh:
            active = self.find_active_qr(account_id)
            if active is not None:
                return active

        await self.stop_session(account_id)
        await self.stop_qr(account_id)
        client = TelegramAccountClient(account_id=account_id, state_instance="starting", running=True)
        self._clients[account_id] = client

        task = asyncio.create_task(
            run_telegram_qr_worker(
                settings=self._settings,
                account_id=account_id,
                credentials=credentials,
                client_state=client,
                manager=self,
            ),
            name=f"telegram-qr-{account_id[:8]}",
        )
        self._qr_tasks[account_id] = task
        task.add_done_callback(lambda _task: self._qr_tasks.pop(account_id, None))

        proxy = resolve_telegram_proxy(settings=self._settings, credentials=credentials)
        deadline = time.time() + telegram_qr_wait_timeout(proxy)
        while time.time() < deadline:
            if client.qr_link and client.track_id:
                return client
            if client.state_instance == "error":
                raise MessengerClientUnavailableError(client.error or "qr failed")
            if client.state_instance == "authorized" or client.is_authorized:
                return client
            await asyncio.sleep(0.25)

        if client.error:
            raise MessengerClientUnavailableError(client.error)
        raise MessengerClientUnavailableError(
            "qr not available: telegram did not respond in time "
            "(check outbound access to Telegram or set TELEGRAM_PROXY in .env)"
        )

    async def stop_qr(self, account_id: str) -> None:
        task = self._qr_tasks.pop(account_id, None)
        if task is not None and not task.done():
            client = self._clients.get(account_id)
            if client is not None:
                client.running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._password_queues.pop(account_id, None)

    async def stop_session(self, account_id: str) -> None:
        task = self._session_tasks.pop(account_id, None)
        if task is not None and not task.done():
            client = self._clients.get(account_id)
            if client is not None:
                client.running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def wait_password(self, account_id: str) -> str:
        queue = self._password_queues.setdefault(account_id, asyncio.Queue())
        return await queue.get()

    async def submit_password(self, account_id: str, password: str) -> None:
        if not password.strip():
            raise ValidationError("password is required")
        client = self._clients.get(account_id)
        if client is None or client.state_instance != "passwordRequired":
            queue = self._password_queues.get(account_id)
            if queue is None:
                raise ValidationError("password is not required")
        else:
            queue = self._password_queues.setdefault(account_id, asyncio.Queue())
        await queue.put(password.strip())

    async def send_message(
        self,
        account_id: str,
        *,
        text: str,
        chat_id: str | None = None,
        phone_number: str | None = None,
        reply_to_external_id: str | None = None,
    ) -> tuple[str, str]:
        if not text.strip():
            raise ValidationError("text is required")

        chat_key = str(chat_id or "").strip()
        phone_key = str(phone_number or "").strip()
        if not chat_key and not phone_key:
            raise ValidationError("chat_id or phone_number is required")
        if chat_key and phone_key:
            raise ValidationError("provide chat_id or phone_number, not both")

        telethon = await self._require_telethon_client(account_id)
        await self._ensure_entity_cache(account_id, telethon)
        peer, resolved_chat_id = await self._resolve_send_target(
            telethon,
            account_id=account_id,
            chat_id=chat_key or None,
            phone_number=phone_key or None,
        )
        reply_to = None
        if reply_to_external_id:
            try:
                reply_to = int(str(reply_to_external_id).strip())
            except ValueError as exc:
                raise ValidationError("reply_to_external_id must be numeric for telegram") from exc
        message = await telethon.send_message(peer, text.strip(), reply_to=reply_to)
        message_id = str(getattr(message, "id", "") or uuid.uuid4().hex)
        title, is_group, external_chat_id = await describe_peer(telethon, message.peer_id)
        if not external_chat_id:
            external_chat_id = resolved_chat_id

        entity = await telethon.get_entity(message.peer_id)
        access_hash = getattr(entity, "access_hash", None)
        avatar_url = await entity_avatar_url(
            telethon,
            entity,
            account_id=account_id,
            external_chat_id=external_chat_id,
            media_storage=getattr(self, "_media_storage", None),
        )

        client_state = self.client_for_account(account_id)
        from_id = str(getattr(client_state, "user_id", "") or "").strip()
        if not from_id:
            credentials = self._creds.get_or_empty(account_id)
            from_id = str(credentials.get("user_id") or account_id)

        sent_at = getattr(message, "date", None) or datetime.now(UTC)
        metadata: dict[str, Any] = {"emit_ws": False}
        if access_hash is not None:
            metadata["access_hash"] = access_hash
        if avatar_url:
            metadata["avatar_url"] = avatar_url
        await self._sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="telegram",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                text=text.strip(),
                from_id=from_id,
                sent_at=sent_at,
                title=title,
                is_group=is_group,
                metadata=metadata,
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
        from telethon.errors import RPCError
        from telethon.tl.functions.messages import SendReactionRequest
        from telethon.tl.types import ReactionEmoji

        telethon = await self._require_telethon_client(account_id)
        await self._ensure_entity_cache(account_id, telethon)
        peer, _ = await self._resolve_send_target(
            telethon,
            account_id=account_id,
            chat_id=chat_id,
            phone_number=None,
        )
        try:
            msg_id = int(str(external_message_id).strip())
        except ValueError as exc:
            raise ValidationError("external_message_id must be numeric for telegram") from exc
        emoticon = _normalize_telegram_reaction_emoji(emoji)
        try:
            await telethon(
                SendReactionRequest(
                    peer=peer,
                    msg_id=msg_id,
                    reaction=[ReactionEmoji(emoticon=emoticon)],
                )
            )
        except RPCError as exc:
            raise ValidationError(f"failed to send telegram reaction: {exc}") from exc

    async def remove_reaction(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
    ) -> None:
        from telethon.errors import RPCError
        from telethon.tl.functions.messages import SendReactionRequest

        telethon = await self._require_telethon_client(account_id)
        await self._ensure_entity_cache(account_id, telethon)
        peer, _ = await self._resolve_send_target(
            telethon,
            account_id=account_id,
            chat_id=chat_id,
            phone_number=None,
        )
        try:
            msg_id = int(str(external_message_id).strip())
        except ValueError as exc:
            raise ValidationError("external_message_id must be numeric for telegram") from exc
        try:
            await telethon(
                SendReactionRequest(
                    peer=peer,
                    msg_id=msg_id,
                    reaction=[],
                )
            )
        except RPCError as exc:
            raise ValidationError(f"failed to remove telegram reaction: {exc}") from exc

    async def forward_message(
        self,
        account_id: str,
        *,
        source_chat_id: str,
        external_message_id: str,
        target_chat_id: str,
    ) -> tuple[str, str]:
        telethon = await self._require_telethon_client(account_id)
        await self._ensure_entity_cache(account_id, telethon)
        from_peer, _ = await self._resolve_send_target(
            telethon,
            account_id=account_id,
            chat_id=source_chat_id,
            phone_number=None,
        )
        to_peer, resolved_target = await self._resolve_send_target(
            telethon,
            account_id=account_id,
            chat_id=target_chat_id,
            phone_number=None,
        )
        try:
            msg_id = int(str(external_message_id).strip())
        except ValueError as exc:
            raise ValidationError("external_message_id must be numeric for telegram") from exc

        results = await telethon.forward_messages(to_peer, [msg_id], from_peer)
        forwarded = results[0] if isinstance(results, list) and results else results
        message_id = str(getattr(forwarded, "id", "") or uuid.uuid4().hex)
        title, is_group, external_chat_id = await describe_peer(telethon, to_peer)
        if not external_chat_id:
            external_chat_id = resolved_target

        text = str(getattr(forwarded, "message", "") or "").strip()
        client_state = self.client_for_account(account_id)
        from_id = str(getattr(client_state, "user_id", "") or account_id)
        sent_at = getattr(forwarded, "date", None) or datetime.now(UTC)
        await self._sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="telegram",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                text=text,
                from_id=from_id,
                sent_at=sent_at,
                title=title or external_chat_id,
                is_group=is_group,
                metadata={"emit_ws": False},
            )
        )
        return message_id, external_chat_id

    async def delete_message(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
    ) -> None:
        telethon = await self._require_telethon_client(account_id)
        await self._ensure_entity_cache(account_id, telethon)
        peer, _ = await self._resolve_send_target(
            telethon,
            account_id=account_id,
            chat_id=chat_id,
            phone_number=None,
        )
        try:
            msg_id = int(str(external_message_id).strip())
        except ValueError as exc:
            raise ValidationError("external_message_id must be numeric for telegram") from exc
        await telethon.delete_messages(peer, [msg_id], revoke=True)

    async def request_call(
        self,
        account_id: str,
        *,
        chat_id: str,
        video: bool = False,
        record_call: bool = False,
        operator_user_id: str = "",
    ) -> dict[str, object]:
        chat_key = str(chat_id or "").strip()
        if not chat_key:
            raise ValidationError("chat_id is required")

        telethon = await self._require_telethon_client(account_id)
        await self._ensure_entity_cache(account_id, telethon)

        from allchats_sdk.providers.telegram.calls import telegram_call_coordinator

        telegram_call_coordinator.register_handlers(telethon, account_id)
        peer = await resolve_send_entity(telethon, chat_key)
        peer_title = None
        try:
            title, _is_group, external_id = await describe_peer(telethon, peer)
            peer_title = title
            chat_key = external_id or chat_key
        except Exception:
            external_id = chat_key
        return await telegram_call_coordinator.request_call(
            telethon,
            account_id=account_id,
            peer=peer,
            video=video,
            record_call=record_call,
            operator_user_id=operator_user_id,
            chat_id=None,
            peer_title=peer_title,
            peer_external_id=chat_key,
        )

    async def require_client(self, account_id: str) -> Any:
        return await self._require_telethon_client(account_id)

    async def ensure_dialog_cache(self, account_id: str, telethon: Any) -> None:
        await self._ensure_entity_cache(account_id, telethon)

    async def _require_telethon_client(self, account_id: str) -> Any:
        client_state = self.client_for_account(account_id)
        if self._is_session_ready(client_state):
            telethon = client_state.telethon_client
            if not telethon.is_connected():
                await telethon.connect()
            return telethon

        credentials = self._creds.get_or_empty(account_id)
        if not credentials:
            raise ValidationError(f"no credentials for connection: {account_id}")
        await self.connect_account(account_id, credentials)
        client_state = self.client_for_account(account_id)
        if not self._is_session_ready(client_state):
            error = client_state.error if client_state is not None else "connect failed"
            raise MessengerClientUnavailableError(
                error or "telegram client is not connected"
            )
        telethon = client_state.telethon_client
        assert telethon is not None
        if not telethon.is_connected():
            await telethon.connect()
        return telethon

    async def _ensure_entity_cache(self, account_id: str, telethon: Any) -> None:
        client_state = self.client_for_account(account_id)
        if client_state is not None and client_state.entities_loaded:
            return
        await ensure_entity_cache(telethon)
        if client_state is not None:
            client_state.entities_loaded = True

    async def _resolve_send_target(
        self,
        client: Any,
        *,
        account_id: str,
        chat_id: str | None,
        phone_number: str | None,
    ) -> tuple[Any, str]:
        if phone_number:
            from telethon.tl.functions.contacts import ResolvePhoneRequest

            phone = phone_number.strip()
            if not phone.startswith("+"):
                phone = f"+{phone.lstrip('+')}"
            result = await client(ResolvePhoneRequest(phone=phone))
            if not result.users:
                raise ValidationError(f"phone number not found: {phone_number}")
            user = result.users[0]
            return user, str(user.id)

        assert chat_id is not None
        entity = await resolve_send_entity(client, chat_id)
        from telethon import utils

        return entity, str(utils.get_peer_id(entity))

    @staticmethod
    def to_qr_response(client: TelegramAccountClient) -> dict[str, Any]:
        return {
            "type": "qrCode",
            "qr_link": client.qr_link,
            "track_id": client.track_id,
            "polling_interval": client.polling_interval or 3000,
            "expires_at": client.expires_at,
        }
