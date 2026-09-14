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


class ConnectionStatus(str, Enum):
    """Typed connection / auth status values."""

    UNKNOWN = "unknown"
    STARTING = "starting"
    AUTHORIZED = "authorized"
    PASSWORD_REQUIRED = "passwordRequired"
    SMS_REQUIRED = "smsRequired"
    CAPTCHA_REQUIRED = "captchaRequired"
    NOT_AUTHORIZED = "notAuthorized"
    ERROR = "error"
    STOPPED = "stopped"


def normalize_connection_status(raw: str | ConnectionStatus | None) -> ConnectionStatus:
    if isinstance(raw, ConnectionStatus):
        return raw
    value = str(raw or "").strip()
    if not value:
        return ConnectionStatus.UNKNOWN
    try:
        return ConnectionStatus(value)
    except ValueError:
        lowered = value.lower()
        for item in ConnectionStatus:
            if item.value.lower() == lowered or item.name.lower() == lowered:
                return item
        return ConnectionStatus.UNKNOWN


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
    """Runtime connection / auth state for an account.

    Typed status constants are available as class attributes::

        ConnectionState.AUTHORIZED
        ConnectionState.PASSWORD_REQUIRED
    """

    AUTHORIZED = ConnectionStatus.AUTHORIZED
    PASSWORD_REQUIRED = ConnectionStatus.PASSWORD_REQUIRED
    SMS_REQUIRED = ConnectionStatus.SMS_REQUIRED
    CAPTCHA_REQUIRED = ConnectionStatus.CAPTCHA_REQUIRED
    NOT_AUTHORIZED = ConnectionStatus.NOT_AUTHORIZED
    STARTING = ConnectionStatus.STARTING
    ERROR = ConnectionStatus.ERROR
    STOPPED = ConnectionStatus.STOPPED
    UNKNOWN = ConnectionStatus.UNKNOWN

    connection_id: str
    state: ConnectionStatus
    user_id: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_raw(cls, account_id: str, raw: Any | None) -> ConnectionState:
        if raw is None:
            return cls(connection_id=account_id, state=ConnectionStatus.UNKNOWN)
        state_raw = getattr(raw, "state_instance", None)
        if state_raw is None and isinstance(raw, dict):
            state_raw = raw.get("state_instance") or raw.get("state")
        user_id = str(getattr(raw, "user_id", None) or (raw.get("user_id") if isinstance(raw, dict) else "") or "")
        error = str(getattr(raw, "error", None) or (raw.get("error") if isinstance(raw, dict) else "") or "")
        status = normalize_connection_status(state_raw)
        if status == ConnectionStatus.UNKNOWN and user_id:
            status = ConnectionStatus.AUTHORIZED
        return cls(
            connection_id=account_id,
            state=status,
            user_id=user_id,
            error=error,
        )

    @property
    def is_authorized(self) -> bool:
        return self.state == ConnectionStatus.AUTHORIZED or bool(self.user_id.strip())

    @property
    def is_password_required(self) -> bool:
        return self.state == ConnectionStatus.PASSWORD_REQUIRED

    @property
    def is_error(self) -> bool:
        return self.state == ConnectionStatus.ERROR


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
