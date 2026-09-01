"""Neutral messenger-sdk models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class OutgoingMessage:
    text: str = ""
    reply_to_external_id: str | None = None
    media: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SentMessage:
    external_message_id: str
    external_chat_id: str
    text: str = ""
    sent_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dialog:
    external_chat_id: str
    title: str = ""
    is_group: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectionState:
    connection_id: str
    state: str
    user_id: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthChallenge:
    connection_id: str
    kind: str  # qr | sms | password | captcha | oauth
    payload: dict[str, Any] = field(default_factory=dict)
