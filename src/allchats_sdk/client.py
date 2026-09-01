"""Unified MessengerClient facade over ProviderRegistry and host-managed MAX sessions."""

from __future__ import annotations

from typing import Any

from allchats_sdk.capabilities import ChatReader, MessageSender, MessengerAuthenticator
from allchats_sdk.errors import MessengerClientUnavailableError, UnsupportedCapabilityError
from allchats_sdk.protocols import CredentialStorage, MessengerProvider
from allchats_sdk.registry import ProviderRegistry, default_registry


class _RegistryMessageSender:
    def __init__(self, provider: Any, account_id: str, provider_id: str) -> None:
        self._provider = provider
        self._account_id = account_id
        self._provider_id = provider_id

    async def send(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        phone_number: str | None = None,
        reply_to_external_id: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str]:
        send = getattr(self._provider, "send_message", None)
        if send is None:
            raise UnsupportedCapabilityError(self._provider_id, "messages.send")
        return await send(
            self._account_id,
            text=text,
            chat_id=chat_id,
            phone_number=phone_number,
            reply_to_external_id=reply_to_external_id,
            **kwargs,
        )


class _RegistryChatReader:
    def __init__(self, provider: Any, account_id: str, provider_id: str) -> None:
        self._provider = provider
        self._account_id = account_id
        self._provider_id = provider_id

    async def client_state(self) -> Any:
        getter = getattr(self._provider, "client_for_account", None)
        if getter is None:
            raise UnsupportedCapabilityError(self._provider_id, "chats.client_state")
        return getter(self._account_id)

    async def sync(self) -> Any:
        sync = getattr(self._provider, "sync_channels_for_account", None)
        if sync is not None:
            return await sync(self._account_id)
        ensure = getattr(self._provider, "ensure_sync", None)
        if ensure is not None:
            credentials = self._credentials()
            return await ensure(self._account_id, credentials)
        raise UnsupportedCapabilityError(self._provider_id, "chats.sync")

    def _credentials(self) -> dict[str, Any]:
        creds = getattr(self._provider, "_creds", None)
        if creds is not None and hasattr(creds, "get_or_empty"):
            return creds.get_or_empty(self._account_id)
        return {}


class _RegistryAuthenticator:
    def __init__(
        self,
        provider: Any,
        account_id: str,
        provider_id: str,
        credential_storage: CredentialStorage | None,
    ) -> None:
        self._provider = provider
        self._account_id = account_id
        self._provider_id = provider_id
        self._credential_storage = credential_storage

    async def connect(self, credentials: dict[str, Any]) -> Any:
        connect = getattr(self._provider, "connect_account", None)
        if connect is None:
            raise UnsupportedCapabilityError(self._provider_id, "auth.connect")
        return await connect(self._account_id, credentials)

    async def start_qr(
        self,
        credentials: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        start_qr = getattr(self._provider, "start_qr", None)
        if start_qr is None:
            raise UnsupportedCapabilityError(self._provider_id, "auth.start_qr")
        creds = credentials or await self._load_credentials()
        try:
            return await start_qr(self._account_id, creds, **kwargs)
        except TypeError:
            return await start_qr(self._account_id, **kwargs)

    async def disconnect(self) -> None:
        disconnect = getattr(self._provider, "disconnect", None)
        if disconnect is None:
            raise UnsupportedCapabilityError(self._provider_id, "auth.disconnect")
        await disconnect(self._account_id)

    async def _load_credentials(self) -> dict[str, Any]:
        if self._credential_storage is None:
            return {}
        stored = await self._credential_storage.get(self._account_id)
        return dict(stored or {})


class MessengerClient:
    """Thin per-account facade over a registry-backed provider manager."""

    def __init__(
        self,
        provider_id: str,
        account_id: str,
        *,
        registry: ProviderRegistry | None = None,
        provider: MessengerProvider | Any | None = None,
        credential_storage: CredentialStorage | None = None,
        **provider_kwargs: Any,
    ) -> None:
        self.provider_id = provider_id.strip().lower()
        self.account_id = account_id.strip()
        if not self.account_id:
            raise ValueError("account_id is required")
        self._credential_storage = credential_storage
        if provider is not None:
            self._provider = provider
        else:
            target = registry or default_registry
            self._provider = target.create(self.provider_id, **provider_kwargs)

    @classmethod
    def from_provider(
        cls,
        provider_id: str,
        account_id: str,
        provider: Any,
        *,
        credential_storage: CredentialStorage | None = None,
    ) -> MessengerClient:
        return cls(
            provider_id,
            account_id,
            provider=provider,
            credential_storage=credential_storage,
        )

    @property
    def provider(self) -> Any:
        return self._provider

    @property
    def messages(self) -> MessageSender:
        if not hasattr(self._provider, "send_message"):
            raise UnsupportedCapabilityError(self.provider_id, "messages")
        return _RegistryMessageSender(self._provider, self.account_id, self.provider_id)

    @property
    def chats(self) -> ChatReader:
        if not (
            hasattr(self._provider, "client_for_account")
            or hasattr(self._provider, "sync_channels_for_account")
            or hasattr(self._provider, "ensure_sync")
        ):
            raise UnsupportedCapabilityError(self.provider_id, "chats")
        return _RegistryChatReader(self._provider, self.account_id, self.provider_id)

    @property
    def auth(self) -> MessengerAuthenticator | None:
        if not (
            hasattr(self._provider, "connect_account")
            or hasattr(self._provider, "start_qr")
            or hasattr(self._provider, "disconnect")
        ):
            return None
        return _RegistryAuthenticator(
            self._provider,
            self.account_id,
            self.provider_id,
            self._credential_storage,
        )

    async def connect(self, credentials: dict[str, Any] | None = None) -> Any:
        creds = credentials
        if creds is None and self._credential_storage is not None:
            stored = await self._credential_storage.get(self.account_id)
            creds = dict(stored or {})
        connect = getattr(self._provider, "connect_account", None)
        if connect is None:
            raise UnsupportedCapabilityError(self.provider_id, "connect")
        return await connect(self.account_id, creds or {})

    async def disconnect(self) -> None:
        auth = self.auth
        if auth is None:
            raise UnsupportedCapabilityError(self.provider_id, "disconnect")
        await auth.disconnect()


class _MaxMessageSender:
    def __init__(self, session_host: Any, account_id: str) -> None:
        self._host = session_host
        self._account_id = account_id

    async def send(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        phone_number: str | None = None,
        reply_to_external_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if phone_number:
            send_by_phone = getattr(self._host, "send_message_by_phone", None)
            if send_by_phone is None:
                raise UnsupportedCapabilityError("max", "messages.send_by_phone")
            runtime = self._require_runtime()
            reply_to = _optional_int(reply_to_external_id)
            return await send_by_phone(
                runtime.snapshot.session_id,
                phone_number,
                text,
                reply_to=reply_to,
                **kwargs,
            )
        if chat_id is None:
            raise ValueError("chat_id or phone_number is required")
        runtime = self._require_runtime()
        reply_to = _optional_int(reply_to_external_id)
        return await self._host.send_message(
            runtime.snapshot.session_id,
            int(chat_id),
            text,
            reply_to=reply_to,
            **kwargs,
        )

    def _require_runtime(self) -> Any:
        finder = getattr(self._host, "find_account_runtime", None)
        if finder is None:
            raise MessengerClientUnavailableError("max session host does not expose find_account_runtime")
        runtime = finder(self._account_id)
        if runtime is None:
            raise MessengerClientUnavailableError("max session is not connected")
        return runtime


class _MaxAuthenticator:
    def __init__(self, session_host: Any, account_id: str) -> None:
        self._host = session_host
        self._account_id = account_id

    async def connect(self, credentials: dict[str, Any]) -> Any:
        _ = credentials
        return await self._host.connect_account(self._account_id)

    async def start_qr(
        self,
        credentials: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        _ = kwargs
        if credentials is None:
            raise ValueError("credentials are required for max QR auth")
        return await self._host.start_qr_for_account(self._account_id, credentials)

    async def disconnect(self) -> None:
        stop = getattr(self._host, "stop_account_sessions", None)
        if stop is None:
            raise UnsupportedCapabilityError("max", "auth.disconnect")
        await stop(self._account_id)


class MaxMessengerClient:
    """Adapter when MAX sessions are orchestrated by the host SessionManager."""

    provider_id = "max"

    def __init__(self, account_id: str, *, session_host: Any) -> None:
        self.account_id = account_id.strip()
        if not self.account_id:
            raise ValueError("account_id is required")
        self._host = session_host

    @property
    def messages(self) -> MessageSender:
        return _MaxMessageSender(self._host, self.account_id)

    @property
    def auth(self) -> MessengerAuthenticator:
        return _MaxAuthenticator(self._host, self.account_id)

    async def connect(self, credentials: dict[str, Any] | None = None) -> Any:
        _ = credentials
        return await self._host.connect_account(self.account_id)

    async def disconnect(self) -> None:
        await self.auth.disconnect()


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return int(raw)
