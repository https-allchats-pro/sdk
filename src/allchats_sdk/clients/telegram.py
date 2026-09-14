"""Public per-account Telegram client."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from allchats_sdk.client import MessengerClient
from allchats_sdk.clients._wiring import load_credentials, resolve_event_sink
from allchats_sdk.credential_store import CredentialStore
from allchats_sdk.protocols import EventSink, IncomingMessageHandler
from allchats_sdk.providers.telegram.provider import TelegramProvider


class TelegramClient:
    """Account-scoped Telegram facade.

    Preferred public entrypoint::

        store = FileCredentialStore("./telegram-session.json")
        client = TelegramClient(
            account_id="acc-1",
            app_id=12345,
            app_hash="...",
            credential_store=store,
        )
        await client.auth.start_qr()
        # session is persisted automatically via credential_store

    Internally: ``TelegramClient`` → ``TelegramProvider`` → ``MessengerClient``.
    """

    provider_id = "telegram"

    def __init__(
        self,
        account_id: str,
        *,
        app_id: int,
        app_hash: str,
        credential_store: CredentialStore | None = None,
        event_sink: EventSink | None = None,
        incoming_handler: IncomingMessageHandler | None = None,
        proxy: Any | None = None,
        credential_storage: CredentialStore | None = None,
    ) -> None:
        account_key = str(account_id or "").strip()
        if not account_key:
            raise ValueError("account_id is required")
        if not app_id:
            raise ValueError("app_id is required")
        hash_value = str(app_hash or "").strip()
        if not hash_value:
            raise ValueError("app_hash is required")

        store = credential_store if credential_store is not None else credential_storage
        settings = SimpleNamespace(
            telegram=SimpleNamespace(app_id=int(app_id), app_hash=hash_value, proxy=proxy),
        )
        self._store = store
        self._provider = TelegramProvider(
            settings=settings,
            event_sink=resolve_event_sink(credential_store=store, event_sink=event_sink),
            incoming_handler=incoming_handler,
        )
        self._client = MessengerClient(
            provider=self._provider,
            account_id=account_key,
            credential_storage=store,
        )
        self.account_id = self._client.account_id

    @property
    def credential_store(self) -> CredentialStore | None:
        return self._store

    @property
    def provider(self) -> TelegramProvider:
        return self._provider

    @property
    def messages(self) -> Any:
        return self._client.messages

    @property
    def chats(self) -> Any:
        return self._client.chats

    @property
    def auth(self) -> Any:
        return self._client.auth

    async def connect(self, credentials: dict[str, Any] | None = None) -> ConnectionState:
        from allchats_sdk.models import ConnectionState

        creds = credentials
        if creds is None:
            creds = await load_credentials(
                self._store,
                self.account_id,
                defaults={"user_id": "", "session_data": ""},
            )
        raw = await self._client.connect(creds)
        if self.auth is not None and hasattr(self.auth, "get_state"):
            return await self.auth.get_state()
        return ConnectionState.from_raw(self.account_id, raw)

    async def disconnect(self) -> None:
        await self._client.disconnect()
