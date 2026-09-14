"""Deprecated compatibility package.

Use ``allchats_sdk.protocols`` for EventSink / MaxSessionHost / storage protocols.
"""

from __future__ import annotations

from allchats_sdk.protocols import (
    EventSink,
    MaxSessionHost,
    NullEventSink,
    SessionManager,
    SessionRuntime,
)

__all__ = [
    "EventSink",
    "MaxSessionHost",
    "NullEventSink",
    "SessionManager",
    "SessionRuntime",
]
