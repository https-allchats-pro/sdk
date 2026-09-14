"""Public per-account VK client."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from allchats_sdk.client import MessengerClient
from allchats_sdk.clients._wiring import load_credentials, resolve_event_sink
from allchats_sdk.credential_store import CredentialStore
from allchats_sdk.protocols import EventSink, IncomingMessageHandler
from allchats_sdk.providers.vk.provider import VKProvider


class VKClient:
    """Account-scoped VK facade.

    Preferred public entrypoint::

        store = FileCredentialStore("./vk-session.json")
        client = VKClient(account_id="acc-1", app_id="12345678", credential_store=store)
        await client.auth.start_qr()

    Internally: ``VKClient`` → ``VKProvider`` → ``MessengerClient``.
    """

    provider_id = "vk"

    def __init__(
        self,
        account_id: str,
        *,
        app_id: str = "",
        app_secret: str = "",
        redirect_uri: str = "",
        scopes: str = "",
        credential_store: CredentialStore | None = None,
        event_sink: EventSink | None = None,
        incoming_handler: IncomingMessageHandler | None = None,
        credential_storage: CredentialStore | None = None,
    ) -> None:
        account_key = str(account_id or "").strip()
        if not account_key:
            raise ValueError("account_id is required")

        app_id_value = str(app_id or "").strip()
        app_secret_value = str(app_secret or "").strip()
        redirect_uri_value = str(redirect_uri or "").strip()
        scopes_value = str(scopes or "").strip()
        store = credential_store if credential_store is not None else credential_storage

        settings = SimpleNamespace(
            vk=SimpleNamespace(
                app_id=app_id_value,
                app_secret=app_secret_value,
                redirect_uri=redirect_uri_value,
                scopes=scopes_value,
                is_configured=lambda: bool(
                    app_id_value and app_secret_value and redirect_uri_value
                ),
                login_auth_configured=lambda: bool(app_id_value),
            )
        )
        self._store = store
        self._provider = VKProvider(
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
    def provider(self) -> VKProvider:
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
            creds = await load_credentials(self._store, self.account_id)
        raw = await self._client.connect(creds)
        if self.auth is not None and hasattr(self.auth, "get_state"):
            return await self.auth.get_state()
        return ConnectionState.from_raw(self.account_id, raw)

    async def disconnect(self) -> None:
        await self._client.disconnect()
