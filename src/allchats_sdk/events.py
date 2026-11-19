"""Event payloads emitted by providers toward the host EventSink."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class IncomingMessageEvent:
    connection_id: str
    provider: str
    external_chat_id: str
    external_message_id: str
    from_id: str
    text: str
    sent_at: datetime | None = None
    title: str = ""
    is_group: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutgoingMessageEvent:
    connection_id: str
    provider: str
    external_chat_id: str
    external_message_id: str
    text: str
    from_id: str = ""
    sent_at: datetime | None = None
    title: str = ""
    is_group: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CredentialsUpdatedEvent:
    connection_id: str
    provider: str
    credentials: dict[str, Any]
    user_id: str = ""
    nickname: str | None = None
    clear: bool = False


@dataclass
class ConnectionStateEvent:
    connection_id: str
    provider: str
    state: str
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatsDiscoveredEvent:
    """Provider discovered chats/channels (initial sync or runtime ready)."""

    connection_id: str
    provider: str
    chats: list[dict[str, Any]] = field(default_factory=list)
    runtime: Any = None  # opaque provider client when host must finish sync


@dataclass
class ChatIdRemapEvent:
    connection_id: str
    provider: str
    chat_key: str
    external_chat_id: str


@dataclass
class MessageReactionsUpdatedEvent:
    """Full reaction map for a message (emoji -> list of actor user ids)."""

    connection_id: str
    provider: str
    external_chat_id: str
    external_message_id: str
    reactions: dict[str, list[str]]


@dataclass
class MessageReactionDeltaEvent:
    connection_id: str
    provider: str
    external_chat_id: str
    external_message_id: str
    emoji: str
    actor_id: str
    added: bool


@dataclass
class TypingEvent:
    """Someone started typing in a chat. Ephemeral — hosts should not persist it."""

    connection_id: str
    provider: str
    external_chat_id: str
    user_id: str
    user_name: str = ""


async def publish_typing(event_sink: Any, event: TypingEvent) -> None:
    """Notify the host when it implements typing. Older sinks stay untouched."""
    handler = getattr(event_sink, "on_typing", None)
    if handler is None:
        return
    await handler(event)
