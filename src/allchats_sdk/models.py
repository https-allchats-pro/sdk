"""Neutral public domain models for allchats-sdk consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Capability(str, Enum):
    """High-level capabilities exposed by :class:`~allchats_sdk.client.MessengerClient`."""

    MESSAGES = "messages"
    CHATS = "chats"
    AUTH = "auth"


@dataclass
class Message:
    """Provider-agnostic message DTO."""

    id: str
    chat_id: str
    text: str = ""
    from_id: str = ""
    account_id: str = ""
    provider: str = ""
    sent_at: datetime | None = None
    title: str = ""
    is_group: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Chat:
    """Provider-agnostic chat / dialog DTO."""

    id: str
    title: str = ""
    is_group: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Account:
    """Linked messenger account identity."""

    id: str
    provider: str
    user_id: str = ""
    state: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectionState:
    """Runtime connection / auth state for an account."""

    connection_id: str
    state: str
    user_id: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# --- Internal / transitional helpers (not part of the stable public surface) ---


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


#: Backward-compatible alias; prefer :class:`Chat`.
Dialog = Chat


@dataclass
class AuthChallenge:
    connection_id: str
    kind: str  # qr | sms | password | captcha | oauth
    payload: dict[str, Any] = field(default_factory=dict)
