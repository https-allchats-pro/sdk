"""Deprecated compatibility shim for host ports.

Use ``allchats_sdk.protocols`` instead::

    from allchats_sdk.protocols import EventSink, MaxSessionHost, SessionManager
"""

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
