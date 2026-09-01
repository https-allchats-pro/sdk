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
