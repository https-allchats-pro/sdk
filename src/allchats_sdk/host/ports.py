"""Deprecated compatibility shim.

Use ``allchats_sdk.protocols`` or ``allchats_sdk.internal.runtime.ports``.
"""

from __future__ import annotations

from allchats_sdk.internal.runtime.ports import (
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
