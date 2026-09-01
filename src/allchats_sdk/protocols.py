"""Unified messenger provider protocols."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from allchats_sdk.events import (
    ChatIdRemapEvent,
    ChatsDiscoveredEvent,
    ConnectionStateEvent,
    CredentialsUpdatedEvent,
    IncomingMessageEvent,
    OutgoingMessageEvent,
)
from allchats_sdk.host_ports import (
    CredentialStorage,
    DeliveryTracker,
    IncomingMessageHandler,
    MediaStorage,
)

__all__ = [
    "CredentialStorage",
    "DeliveryTracker",
    "EventSink",
    "IncomingMessageHandler",
    "MediaStorage",
    "MessengerProvider",
    "NullEventSink",
]


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
    """Pure host callback surface — push only, no DB lookups from the SDK."""

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
