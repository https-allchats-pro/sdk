from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from neonize.aioze.client import NewAClient

from allchats_sdk.providers.whatsapp.client import normalize_recipient, phone_to_chat_id
from allchats_sdk.providers.whatsapp.neonize_runtime import (
    clear_session_dir,
    neonize_client_is_ready,
    revoke_neonize_message,
    run_whatsapp_neonize_runtime,
    send_neonize_message,
    send_neonize_reaction,
    whatsapp_session_db,
)
from allchats_sdk.config import Settings
from allchats_sdk.events import ChatIdRemapEvent, CredentialsUpdatedEvent, OutgoingMessageEvent
from allchats_sdk.protocols import DeliveryTracker, EventSink, IncomingMessageHandler
from allchats_sdk.providers.credentials_cache import CredentialsCache
from allchats_sdk.credentials import merge_credentials, whatsapp_authorized
from allchats_sdk.errors import MessengerClientUnavailableError, ValidationError
from allchats_sdk.internal.observability import record_auth

logger = logging.getLogger(__name__)

RUNTIME_START_TIMEOUT_SEC = 30.0
NEONIZE_READY_TIMEOUT_SEC = 30.0


@dataclass
class WhatsAppAccountClient:
    account_id: str
    state_instance: str = "notAuthorized"
    user_id: str = ""
    error: str = ""
    running: bool = False
    qr_data_url: str = ""
    qr_polling_interval: int = 2000

    @property
    def is_authorized(self) -> bool:
        return self.state_instance == "authorized" or bool(str(self.user_id or "").strip())


class WhatsAppClientManager:
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
        self._clients: dict[str, WhatsAppAccountClient] = {}
        self._neonize_clients: dict[str, NewAClient] = {}
        self._runtime_tasks: dict[str, asyncio.Task[Any]] = {}
        # neonize Go runtime races on concurrent NewAClient/connect (fatal: concurrent map writes).
        self._neonize_bootstrap_lock = asyncio.Lock()

    @property
    def event_sink(self) -> EventSink:
        return self._sink

    @property
    def neonize_bootstrap_lock(self) -> asyncio.Lock:
        return self._neonize_bootstrap_lock

    @property
    def settings(self) -> Settings:
        return self._settings

    def is_configured(self) -> bool:
        return True

    def client_for_account(self, account_id: str) -> WhatsAppAccountClient | None:
        return self._clients.get(account_id)

    def connected_count(self) -> int:
        return len(set(self._clients) | set(self._neonize_clients))

    def neonize_client_for_account(self, account_id: str) -> NewAClient | None:
        return self._neonize_clients.get(account_id)

    def register_neonize_client(self, account_id: str, client: NewAClient) -> None:
        self._neonize_clients[account_id] = client

    def unregister_neonize_client(self, account_id: str) -> None:
        self._neonize_clients.pop(account_id, None)

    def unregister_client(self, account_id: str) -> None:
        self._clients.pop(account_id, None)

    def is_account_busy(self, account_id: str) -> bool:
        client = self._clients.get(account_id)
        if client is None:
            return False
        task = self._runtime_tasks.get(account_id)
        return client.running and task is not None and not task.done()

    def is_qr_login_active(self, account_id: str) -> bool:
        client = self._clients.get(account_id)
        task = self._runtime_tasks.get(account_id)
        if client is None or task is None or task.done():
            return False
        return client.state_instance in {"starting", "qrWaiting"} and not client.is_authorized

    def set_client_state(
        self,
        account_id: str,
        *,
        state_instance: str,
        user_id: str = "",
        error: str = "",
        running: bool = True,
    ) -> WhatsAppAccountClient:
        client = self._clients.get(account_id)
        if client is None:
            client = WhatsAppAccountClient(account_id=account_id)
            self._clients[account_id] = client
        client.state_instance = state_instance
        client.user_id = user_id
        client.error = error
        client.running = running
        return client

    @staticmethod
    def to_qr_response(client: WhatsAppAccountClient) -> dict[str, Any]:
        if client.qr_data_url:
            return {
                "type": "qrCode",
                "data_url": client.qr_data_url,
                "polling_interval": client.qr_polling_interval,
            }
        return {"type": "error", "message": client.error or "QR code is not available"}

    async def _ensure_runtime(self, account_id: str) -> WhatsAppAccountClient:
        existing_task = self._runtime_tasks.get(account_id)
        if existing_task is not None and not existing_task.done():
            client = self._clients.get(account_id)
            if client is not None:
                return client

        client = self.set_client_state(account_id, state_instance="starting", running=True)
        credentials = self._creds.get_or_empty(account_id)
        task = asyncio.create_task(
            run_whatsapp_neonize_runtime(
                settings=self._settings,
                account_id=account_id,
                client_state=client,
                manager=self,
                event_sink=self._sink,
                incoming_handler=self._incoming_handler,
                credentials=credentials,
            ),
            name=f"whatsapp-runtime-{account_id[:8]}",
        )
        self._runtime_tasks[account_id] = task
        task.add_done_callback(lambda _task: self._runtime_tasks.pop(account_id, None))
        return client

    async def _wait_for_qr_or_auth(
        self,
        account_id: str,
        *,
        timeout_sec: float = RUNTIME_START_TIMEOUT_SEC,
    ) -> WhatsAppAccountClient:
        deadline = asyncio.get_running_loop().time() + timeout_sec
        while asyncio.get_running_loop().time() < deadline:
            client = self._clients.get(account_id)
            if client is None:
                await asyncio.sleep(0.2)
                continue
            if client.is_authorized or client.state_instance == "authorized":
                return client
            if client.qr_data_url:
                return client
            if client.error and client.state_instance == "notAuthorized":
                raise ValidationError(client.error)
            await asyncio.sleep(0.25)

        client = self._clients.get(account_id)
        if client is not None and (client.qr_data_url or client.is_authorized):
            return client
        raise ValidationError("QR code is not available yet")

    async def fetch_qr(self, account_id: str) -> dict[str, Any]:
        await self._ensure_runtime(account_id)
        client = await self._wait_for_qr_or_auth(account_id)
        if client.is_authorized or client.state_instance == "authorized":
            return {"type": "alreadyLogged", "message": "Account already authorized"}
        if client.qr_data_url:
            return {
                "type": "qrCode",
                "data_url": client.qr_data_url,
                "polling_interval": client.qr_polling_interval,
            }
        return {"type": "error", "message": client.error or "QR code is not available"}

    async def start_qr(
        self,
        account_id: str,
        *,
        refresh: bool = False,
    ) -> WhatsAppAccountClient:
        credentials = self._creds.get_or_empty(account_id)
        session_db = whatsapp_session_db(self._settings, account_id)

        if refresh:
            await self.stop_runtime(account_id)
            clear_session_dir(self._settings, account_id)
        elif not whatsapp_authorized(credentials) and session_db.exists():
            await self.stop_runtime(account_id)
            clear_session_dir(self._settings, account_id)

        client = self._clients.get(account_id)
        task = self._runtime_tasks.get(account_id)
        if not refresh and task is not None and not task.done() and client is not None:
            if client.qr_data_url or client.is_authorized:
                return client

        client = await self._ensure_runtime(account_id)
        try:
            client = await self._wait_for_qr_or_auth(account_id)
        except ValidationError:
            if client.is_authorized:
                return client
            raise

        if client.is_authorized:
            return client
        return client

    async def stop_runtime(self, account_id: str) -> None:
        task = self._runtime_tasks.pop(account_id, None)
        client = self._clients.get(account_id)
        if client is not None:
            client.running = False
            client.qr_data_url = ""
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def cleanup_qr_auth(self, account_id: str) -> None:
        return

    async def on_authorized(
        self,
        account_id: str,
        *,
        neonize_client: NewAClient | None = None,
    ) -> None:
        existing = self.client_for_account(account_id)
        if existing is not None and existing.state_instance == "authorized" and existing.user_id:
            return

        client_obj = neonize_client or self.neonize_client_for_account(account_id)
        user_id = ""
        nickname = None
        if client_obj is not None and getattr(client_obj, "me", None) is not None:
            me = client_obj.me
            user_id = str(getattr(me, "ID", "") or getattr(getattr(me, "JID", None), "User", "") or "").strip()
            nickname = str(getattr(me, "PushName", "") or user_id or "").strip() or None

        existing = self._creds.get_or_empty(account_id) or {"device_id": account_id}
        merged = merge_credentials(
            existing,
            {
                "protocol": "web",
                "state_instance": "authorized",
                "user_id": user_id,
            },
        )
        self._creds.set(account_id, merged)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="whatsapp",
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
        client.qr_data_url = ""
        record_auth("whatsapp", "success")

    async def get_state(self, account_id: str, credentials: dict[str, Any]) -> str:
        stored_state = str(credentials.get("state_instance") or "").strip()
        if stored_state == "authorized" and whatsapp_authorized(credentials):
            neonize_client = self.neonize_client_for_account(account_id)
            if neonize_client is not None and await neonize_client_is_ready(neonize_client):
                self.set_client_state(
                    account_id,
                    state_instance="authorized",
                    user_id=str(credentials.get("user_id") or ""),
                    running=True,
                )
                return "authorized"

            await self.ensure_client(account_id, credentials)
            neonize_client = self.neonize_client_for_account(account_id)
            if neonize_client is not None and await neonize_client_is_ready(neonize_client):
                self.set_client_state(
                    account_id,
                    state_instance="authorized",
                    user_id=str(credentials.get("user_id") or ""),
                    running=True,
                )
                return "authorized"

        session_db = whatsapp_session_db(self._settings, account_id)
        if session_db.exists():
            try:
                await self._ensure_runtime(account_id)
                client = await self._wait_for_qr_or_auth(account_id, timeout_sec=15.0)
                if client.is_authorized:
                    return "authorized"
                if client.qr_data_url:
                    return "starting"
            except ValidationError:
                pass
            except Exception as exc:
                logger.debug("whatsapp session restore failed account=%s: %s", account_id[:8], exc)

        return stored_state or "notAuthorized"

    async def ensure_client(
        self,
        account_id: str,
        credentials: dict[str, Any],
    ) -> WhatsAppAccountClient:
        self._creds.set(account_id, credentials)
        if whatsapp_authorized(credentials):
            client = self.set_client_state(
                account_id,
                state_instance="authorized",
                user_id=str(credentials.get("user_id") or ""),
                running=True,
            )
            await self._ensure_runtime(account_id)
            return client

        state = await self.get_state(account_id, credentials)
        return self.set_client_state(
            account_id,
            state_instance=state or "notAuthorized",
            running=state == "authorized",
        )

    async def require_neonize_client(
        self,
        account_id: str,
        credentials: dict[str, Any],
        *,
        timeout_sec: float = NEONIZE_READY_TIMEOUT_SEC,
    ) -> NewAClient:
        if not whatsapp_authorized(credentials):
            raise ValidationError("whatsapp account is not authorized")

        await self.ensure_client(account_id, credentials)

        deadline = asyncio.get_running_loop().time() + timeout_sec
        while asyncio.get_running_loop().time() < deadline:
            runtime = self.client_for_account(account_id)
            neonize_client = self.neonize_client_for_account(account_id)
            if (
                neonize_client is not None
                and await neonize_client_is_ready(neonize_client)
            ):
                return neonize_client

            if runtime is not None and runtime.error and runtime.state_instance == "notAuthorized":
                raise MessengerClientUnavailableError(runtime.error)

            await asyncio.sleep(0.25)

        raise MessengerClientUnavailableError("whatsapp client is not ready")

    async def ensure_worker(self, account_id: str) -> None:
        await self._ensure_runtime(account_id)

    async def connect_account(
        self,
        account_id: str,
        credentials: dict[str, Any],
    ) -> WhatsAppAccountClient:
        if not whatsapp_authorized(credentials):
            state = await self.get_state(account_id, credentials)
            if state != "authorized":
                raise ValidationError("account is not authorized")
            credentials = self._creds.get_or_empty(account_id) or credentials
        self._creds.set(account_id, credentials)
        return await self.ensure_client(account_id, credentials)

    async def disconnect(self, account_id: str) -> None:
        await self.stop_runtime(account_id)
        self.unregister_neonize_client(account_id)
        clear_session_dir(self._settings, account_id)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="whatsapp",
                credentials={},
                clear=True,
            )
        )
        self._creds.pop(account_id)
        self.unregister_client(account_id)

    async def send_message(
        self,
        account_id: str,
        *,
        text: str,
        chat_id: str | None = None,
        phone_number: str | None = None,
        reply_to_external_id: str | None = None,
        reply_to_sender: str | None = None,
        reply_to_text: str | None = None,
    ) -> tuple[str, str]:
        trimmed = text.strip()
        if not trimmed:
            raise ValidationError("text is required")

        chat_key = str(chat_id or "").strip()
        phone_key = str(phone_number or "").strip()
        if not chat_key and not phone_key:
            raise ValidationError("chat_id or phone_number is required")
        if chat_key and phone_key:
            raise ValidationError("provide chat_id or phone_number, not both")

        credentials = self._creds.get(account_id)
        if not whatsapp_authorized(credentials):
            raise ValidationError("whatsapp account is not authorized")

        await self.ensure_client(account_id, credentials)
        neonize_client = await self.require_neonize_client(account_id, credentials)

        if chat_key:
            external_chat_id = chat_key
            stored_external_chat_id = external_chat_id
        else:
            recipient = normalize_recipient(phone_key)
            external_chat_id = phone_to_chat_id(recipient)
            stored_external_chat_id = external_chat_id

        recipient = normalize_recipient(
            external_chat_id.split("@", 1)[0] if "@" in external_chat_id else external_chat_id
        )
        if not recipient:
            raise ValidationError("recipient phone number is invalid")

        try:
            message_id, resolved_chat_id = await send_neonize_message(
                neonize_client,
                external_chat_id=external_chat_id,
                phone_digits=recipient,
                text=trimmed,
                session_db=whatsapp_session_db(self._settings, account_id),
                reply_to_external_id=reply_to_external_id,
                reply_to_sender=reply_to_sender,
                reply_to_text=reply_to_text,
            )
        except Exception as exc:
            raise ValidationError(f"failed to send whatsapp message: {exc}") from exc

        if not message_id:
            message_id = uuid.uuid4().hex

        external_chat_id = resolved_chat_id or external_chat_id
        if chat_key and stored_external_chat_id != external_chat_id:
            await self._sink.on_chat_id_remap(
                ChatIdRemapEvent(
                    connection_id=account_id,
                    provider="whatsapp",
                    chat_key=chat_key,
                    external_chat_id=external_chat_id,
                )
            )
        from_id = str(credentials.get("user_id") or account_id)

        await self._sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="whatsapp",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                text=trimmed,
                from_id=from_id,
                sent_at=datetime.now(UTC),
                is_group=external_chat_id.endswith("@g.us"),
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
        sender: str,
    ) -> None:
        credentials = self._creds.get(account_id)
        await self.ensure_client(account_id, credentials)
        neonize_client = await self.require_neonize_client(account_id, credentials)
        external_chat_id = chat_id.strip()
        try:
            await send_neonize_reaction(
                neonize_client,
                external_chat_id=external_chat_id,
                sender_external_id=sender or external_chat_id,
                message_id=external_message_id,
                emoji=emoji,
                session_db=whatsapp_session_db(self._settings, account_id),
            )
        except Exception as exc:
            raise ValidationError(f"failed to send whatsapp reaction: {exc}") from exc

    async def remove_reaction(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
        sender: str,
    ) -> None:
        # Empty reaction removes the previous one in WhatsApp.
        await self.add_reaction(
            account_id,
            chat_id=chat_id,
            external_message_id=external_message_id,
            emoji="",
            sender=sender,
        )

    async def delete_message(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
        sender: str,
        is_incoming: bool = False,
    ) -> None:
        credentials = self._creds.get(account_id)
        await self.ensure_client(account_id, credentials)
        neonize_client = await self.require_neonize_client(account_id, credentials)
        external_chat_id = chat_id.strip()
        sender_id = sender
        if not is_incoming:
            sender_id = str(credentials.get("user_id") or sender or external_chat_id)
        try:
            await revoke_neonize_message(
                neonize_client,
                external_chat_id=external_chat_id,
                sender_external_id=sender_id or external_chat_id,
                message_id=external_message_id,
                session_db=whatsapp_session_db(self._settings, account_id),
            )
        except Exception as exc:
            raise ValidationError(f"failed to delete whatsapp message: {exc}") from exc
