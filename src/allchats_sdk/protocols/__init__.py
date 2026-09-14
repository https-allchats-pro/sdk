"""Application-facing protocols implemented by the host (backend).

Prefer importing from ``allchats_sdk.protocols``::

    from allchats_sdk.protocols import EventSink, MediaStorage, IncomingMessageHandler

Legacy modules ``allchats_sdk.host_ports`` and ``allchats_sdk.host`` re-export
these symbols for compatibility.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from allchats_sdk.events import (
    ChatIdRemapEvent,
    ChatsDiscoveredEvent,
    ConnectionStateEvent,
    CredentialsUpdatedEvent,
    IncomingMessageEvent,
    OutgoingMessageEvent,
)

__all__ = [
    "CredentialStorage",
    "DeliveryTracker",
    "EventSink",
    "IncomingMessageHandler",
    "MaxSessionHost",
    "MediaStorage",
    "MessengerProvider",
    "NullEventSink",
    "SessionManager",
    "SessionRuntime",
]


@runtime_checkable
class MediaStorage(Protocol):
    """Persist downloaded messenger media files."""

    def save_voice(self, *, account_id: str, data: bytes, extension: str) -> str: ...

    def save_media(self, *, account_id: str, data: bytes, extension: str) -> str: ...

    def save_avatar(self, *, account_id: str, external_chat_id: str, data: bytes) -> str: ...


@runtime_checkable
class DeliveryTracker(Protocol):
    """Track outgoing message delivery/read receipts."""

    async def mark_up_to_external_id(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        max_external_id: int,
        status: str,
    ) -> None: ...

    async def mark_by_external_ids(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        external_ids: list[str],
        status: str,
    ) -> None: ...

    async def mark_up_to_sent_at(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        sent_before: datetime | int,
        status: str,
    ) -> None: ...


@runtime_checkable
class IncomingMessageHandler(Protocol):
    """Host handler for rich incoming/outgoing media messages."""

    async def process_telegram_incoming(self, **kwargs: Any) -> bool: ...

    async def process_telegram_outgoing(self, **kwargs: Any) -> Any | None: ...

    async def process_vk_incoming(self, **kwargs: Any) -> bool: ...

    async def process_vk_outgoing(self, **kwargs: Any) -> Any | None: ...

    async def process_whatsapp_incoming(self, **kwargs: Any) -> bool: ...

    async def process_whatsapp_outgoing(self, **kwargs: Any) -> Any | None: ...

    async def process_max_incoming(self, **kwargs: Any) -> Any | None: ...

    async def process_max_outgoing(self, **kwargs: Any) -> Any | None: ...


@runtime_checkable
class CredentialStorage(Protocol):
    """Optional persistent credential store (backend implements).

    Public account clients prefer :class:`~allchats_sdk.credential_store.CredentialStore`.
    """

    async def get(self, account_id: str) -> dict[str, Any] | None: ...

    async def save(self, account_id: str, credentials: dict[str, Any]) -> None: ...

    async def clear(self, account_id: str) -> None: ...


@runtime_checkable
class MessengerProvider(Protocol):
    """Common surface for messenger integrations."""

    provider_id: str

    async def connect(self, connection_id: str, credentials: dict[str, Any]) -> Any: ...

    async def disconnect(self, connection_id: str) -> None: ...

    async def send_message(
        self,
        connection_id: str,
        chat_id: str,
        text: str,
        **kwargs: Any,
    ) -> Any: ...

    async def get_dialogs(self, connection_id: str) -> list[Any]: ...


@runtime_checkable
class EventSink(Protocol):
    """Callback surface for provider events — push only, no DB lookups from the SDK."""

    async def on_incoming(self, event: IncomingMessageEvent) -> None: ...

    async def on_outgoing(self, event: OutgoingMessageEvent) -> None: ...

    async def on_credentials_updated(self, event: CredentialsUpdatedEvent) -> None: ...

    async def on_connection_state(self, event: ConnectionStateEvent) -> None: ...

    async def on_chats_discovered(self, event: ChatsDiscoveredEvent) -> None: ...

    async def on_chat_id_remap(self, event: ChatIdRemapEvent) -> None: ...


class NullEventSink:
    """No-op sink for tests / standalone use."""

    async def on_incoming(self, event: IncomingMessageEvent) -> None:
        return None

    async def on_outgoing(self, event: OutgoingMessageEvent) -> None:
        return None

    async def on_credentials_updated(self, event: CredentialsUpdatedEvent) -> None:
        return None

    async def on_connection_state(self, event: ConnectionStateEvent) -> None:
        return None

    async def on_chats_discovered(self, event: ChatsDiscoveredEvent) -> None:
        return None

    async def on_chat_id_remap(self, event: ChatIdRemapEvent) -> None:
        return None


@runtime_checkable
class MaxSessionHost(Protocol):
    """Host-owned MAX session orchestration (runtime bridge)."""

    async def set_status(self, session_id: str, status: str, **kwargs: Any) -> Any: ...

    async def set_qr_url(self, session_id: str, qr_url: str) -> Any: ...

    async def set_qr_info(self, *args: Any, **kwargs: Any) -> Any: ...

    async def update_qr_watcher(self, *args: Any, **kwargs: Any) -> Any: ...

    async def set_sms_token(self, session_id: str, token: str) -> Any: ...

    async def set_password_challenge(self, *args: Any, **kwargs: Any) -> Any: ...

    async def publish_message(self, *args: Any, **kwargs: Any) -> Any: ...

    async def notify_incoming_message(self, *args: Any, **kwargs: Any) -> Any: ...

    async def on_client_ready(self, session_id: str, client: Any) -> Any: ...


#: Compatibility aliases for MAX runtime typing.
SessionManager = MaxSessionHost
SessionRuntime = Any
