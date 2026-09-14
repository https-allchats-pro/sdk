"""Public per-account MAX client."""

from __future__ import annotations

from typing import Any

from allchats_sdk.client import MessengerClient
from allchats_sdk.credential_store import CredentialStore
from allchats_sdk.providers.max.provider import MAXProvider


class MAXClient:
    """Account-scoped MAX facade over a host-owned SessionManager.

    Preferred public entrypoint::

        client = MAXClient(account_id="acc-1", session_host=session_manager)
        await client.connect()

    Internally: ``MAXClient`` → ``MAXProvider`` → ``MessengerClient``.
    """

    provider_id = "max"

    def __init__(
        self,
        account_id: str,
        *,
        session_host: Any,
        credential_store: CredentialStore | None = None,
        credential_storage: CredentialStore | None = None,
    ) -> None:
        account_key = str(account_id or "").strip()
        if not account_key:
            raise ValueError("account_id is required")
        store = credential_store if credential_store is not None else credential_storage
        self._store = store
        self._provider = MAXProvider(session_host=session_host)
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
    def provider(self) -> MAXProvider:
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

    async def connect(self, credentials: dict[str, Any] | None = None) -> Any:
        return await self._client.connect(credentials)

    async def disconnect(self) -> None:
        await self._client.disconnect()
