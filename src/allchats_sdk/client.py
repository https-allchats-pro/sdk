"""Unified MessengerClient facade over typed providers and host-managed MAX sessions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from allchats_sdk.capabilities import ChatReader, MessageSender, MessengerAuthenticator
from allchats_sdk.errors import MessengerClientUnavailableError, UnsupportedCapabilityError
from allchats_sdk.models import ConnectionState
from allchats_sdk.protocols import CredentialStorage, MessengerProvider
from allchats_sdk.internal.registry import ProviderRegistry, default_registry

_BUILTINS_REGISTERED = False


def _ensure_builtin_providers() -> None:
    global _BUILTINS_REGISTERED
    if _BUILTINS_REGISTERED:
        return
    from allchats_sdk.internal.runtime.register import register_builtin_providers

    register_builtin_providers()
    _BUILTINS_REGISTERED = True


def _resolve_provider_id(provider: Any, fallback: str = "") -> str:
    raw = getattr(provider, "provider_id", None) or fallback
    return str(raw or "").strip().lower()


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
        stop_session = getattr(self._provider, "stop_session", None)
        stop_qr = getattr(self._provider, "stop_qr", None)
        if disconnect is not None:
            await disconnect(self._account_id)
            return
        if stop_qr is not None:
            await stop_qr(self._account_id)
        if stop_session is not None:
            await stop_session(self._account_id)
            return
        raise UnsupportedCapabilityError(self._provider_id, "auth.disconnect")

    async def submit_password(self, password: str) -> None:
        submit = getattr(self._provider, "submit_password", None)
        if submit is None:
            raise UnsupportedCapabilityError(self._provider_id, "auth.submit_password")
        await submit(self._account_id, password)

    async def connect_with_token(self, access_token: str, **kwargs: Any) -> dict[str, Any]:
        connect = getattr(self._provider, "connect_with_token", None)
        if connect is None:
            raise UnsupportedCapabilityError(self._provider_id, "auth.connect_with_token")
        return await connect(self._account_id, access_token=access_token, **kwargs)

    def build_oauth_url(self) -> str:
        build = getattr(self._provider, "build_oauth_authorization_url", None)
        if build is None:
            raise UnsupportedCapabilityError(self._provider_id, "auth.build_oauth_url")
        return build(self._account_id)

    async def connect_with_oauth_code(
        self,
        *,
        code: str,
        oauth_state: str,
        device_id: str = "",
    ) -> dict[str, Any]:
        resolve = getattr(self._provider, "resolve_oauth_account_id", None)
        account_id = self._account_id
        if resolve is not None:
            mapped = resolve(oauth_state)
            if mapped:
                account_id = mapped
        connect = getattr(self._provider, "connect_with_oauth_code", None)
        if connect is None:
            raise UnsupportedCapabilityError(self._provider_id, "auth.connect_with_oauth_code")
        return await connect(
            account_id,
            code=code,
            oauth_state=oauth_state,
            device_id=device_id,
        )

    async def get_state(self) -> ConnectionState:
        getter = getattr(self._provider, "client_for_account", None)
        raw = getter(self._account_id) if getter is not None else None
        return ConnectionState.from_raw(self._account_id, raw)

    async def wait_until_authorized(
        self,
        *,
        timeout_sec: float = 300.0,
        poll_interval_sec: float = 0.5,
        password_provider: Callable[[], Awaitable[str]] | Callable[[], str] | None = None,
    ) -> ConnectionState:
        """Poll provider state until authorized (handles password challenge when provided)."""
        import asyncio
        import inspect

        from allchats_sdk.errors import AllChatsError
        from allchats_sdk.models import ConnectionStatus

        deadline = asyncio.get_running_loop().time() + timeout_sec
        while asyncio.get_running_loop().time() < deadline:
            status = await self.get_state()
            if status.is_password_required:
                if password_provider is None:
                    raise AllChatsError("password required; pass password_provider=...")
                password = password_provider()
                if inspect.isawaitable(password):
                    password = await password
                await self.submit_password(str(password or "").strip())
                await asyncio.sleep(poll_interval_sec)
                continue
            if status.is_authorized:
                return status
            if status.state == ConnectionStatus.ERROR:
                raise AllChatsError(status.error or f"{self._provider_id} auth failed")
            if status.state == ConnectionStatus.NOT_AUTHORIZED and status.error:
                raise AllChatsError(status.error)
            await asyncio.sleep(poll_interval_sec)
        raise TimeoutError(f"{self._provider_id} authorization timed out")

    async def _load_credentials(self) -> dict[str, Any]:
        if self._credential_storage is None:
            return {}
        stored = await self._credential_storage.get(self._account_id)
        return dict(stored or {})


class MessengerClient:
    """Per-account facade over a typed provider (or legacy registry name).

    Preferred::

        telegram = TelegramProvider(settings=settings, event_sink=sink)
        client = MessengerClient(provider=telegram, account_id=account_id)

    Legacy (internal / host) still works::

        MessengerClient("telegram", account_id, settings=..., event_sink=...)
    """

    def __init__(
        self,
        provider_id: str | None = None,
        account_id: str | None = None,
        *,
        provider: MessengerProvider | Any | None = None,
        registry: ProviderRegistry | None = None,
        credential_storage: CredentialStorage | None = None,
        **provider_kwargs: Any,
    ) -> None:
        resolved_account_id = str(account_id or "").strip()
        if not resolved_account_id:
            raise ValueError("account_id is required")
        self.account_id = resolved_account_id
        self._credential_storage = credential_storage
        self._session_host: Any | None = None

        if provider is not None:
            if _resolve_provider_id(provider, provider_id or "") == "max" and hasattr(
                provider, "session_host"
            ):
                self.provider_id = "max"
                self._session_host = getattr(provider, "session_host", provider)
                self._provider = provider
                return

            self.provider_id = _resolve_provider_id(provider, provider_id or "")
            if not self.provider_id:
                raise ValueError("provider must define provider_id")
            self._provider = provider
            return

        legacy_id = str(provider_id or "").strip().lower()
        if not legacy_id:
            raise ValueError("provider or provider_id is required")
        self.provider_id = legacy_id
        _ensure_builtin_providers()
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
        """Backward-compatible constructor; prefer ``MessengerClient(provider=..., account_id=...)``."""
        return cls(
            provider=provider,
            account_id=account_id,
            provider_id=provider_id,
            credential_storage=credential_storage,
        )

    @property
    def provider(self) -> Any:
        return self._provider

    @property
    def messages(self) -> MessageSender:
        if self._session_host is not None:
            return _MaxMessageSender(self._session_host, self.account_id)
        if not hasattr(self._provider, "send_message"):
            raise UnsupportedCapabilityError(self.provider_id, "messages")
        return _RegistryMessageSender(self._provider, self.account_id, self.provider_id)

    @property
    def chats(self) -> ChatReader:
        if self._session_host is not None:
            raise UnsupportedCapabilityError(self.provider_id, "chats")
        if not (
            hasattr(self._provider, "client_for_account")
            or hasattr(self._provider, "sync_channels_for_account")
            or hasattr(self._provider, "ensure_sync")
        ):
            raise UnsupportedCapabilityError(self.provider_id, "chats")
        return _RegistryChatReader(self._provider, self.account_id, self.provider_id)

    @property
    def auth(self) -> MessengerAuthenticator | None:
        if self._session_host is not None:
            return _MaxAuthenticator(self._session_host, self.account_id)
        if not (
            hasattr(self._provider, "connect_account")
            or hasattr(self._provider, "start_qr")
            or hasattr(self._provider, "disconnect")
            or hasattr(self._provider, "stop_session")
        ):
            return None
        return _RegistryAuthenticator(
            self._provider,
            self.account_id,
            self.provider_id,
            self._credential_storage,
        )

    async def connect(self, credentials: dict[str, Any] | None = None) -> Any:
        if self._session_host is not None:
            return await self._session_host.connect_account(self.account_id)
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

    async def submit_password(self, password: str) -> None:
        raise UnsupportedCapabilityError("max", "auth.submit_password")

    async def connect_with_token(self, access_token: str, **kwargs: Any) -> dict[str, Any]:
        raise UnsupportedCapabilityError("max", "auth.connect_with_token")

    def build_oauth_url(self) -> str:
        raise UnsupportedCapabilityError("max", "auth.build_oauth_url")

    async def connect_with_oauth_code(
        self,
        *,
        code: str,
        oauth_state: str,
        device_id: str = "",
    ) -> dict[str, Any]:
        raise UnsupportedCapabilityError("max", "auth.connect_with_oauth_code")

    async def get_state(self) -> ConnectionState:
        from allchats_sdk.models import ConnectionStatus

        finder = getattr(self._host, "find_account_runtime", None)
        runtime = finder(self._account_id) if finder is not None else None
        if runtime is None:
            return ConnectionState(
                connection_id=self._account_id,
                state=ConnectionStatus.NOT_AUTHORIZED,
            )
        return ConnectionState(
            connection_id=self._account_id,
            state=ConnectionStatus.AUTHORIZED,
        )

    async def wait_until_authorized(
        self,
        *,
        timeout_sec: float = 300.0,
        poll_interval_sec: float = 0.5,
        password_provider: Callable[[], Awaitable[str]] | Callable[[], str] | None = None,
    ) -> ConnectionState:
        _ = timeout_sec, poll_interval_sec, password_provider
        status = await self.get_state()
        if status.is_authorized:
            return status
        raise UnsupportedCapabilityError("max", "auth.wait_until_authorized")


class MaxMessengerClient(MessengerClient):
    """Backward-compatible MAX client; prefer ``MessengerClient(provider=MAXProvider(...), ...)``."""

    def __init__(self, account_id: str, *, session_host: Any) -> None:
        from allchats_sdk.providers.max.provider import MAXProvider

        super().__init__(provider=MAXProvider(session_host=session_host), account_id=account_id)


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return int(raw)
