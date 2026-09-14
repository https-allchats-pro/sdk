"""Runtime port aliases — prefer ``allchats_sdk.protocols``."""

from __future__ import annotations

from allchats_sdk.protocols import (
    CredentialStorage,
    DeliveryTracker,
    EventSink,
    IncomingMessageHandler,
    MaxSessionHost,
    MediaStorage,
    NullEventSink,
    SessionManager,
    SessionRuntime,
)

__all__ = [
    "CredentialStorage",
    "DeliveryTracker",
    "EventSink",
    "IncomingMessageHandler",
    "MaxSessionHost",
    "MediaStorage",
    "NullEventSink",
    "SessionManager",
    "SessionRuntime",
]
