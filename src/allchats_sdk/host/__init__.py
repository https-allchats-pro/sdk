"""Deprecated compatibility package.

Use ``allchats_sdk.protocols`` for protocols, or ``allchats_sdk.internal.runtime``
for host-owned runtime bridges.
"""

from __future__ import annotations

from allchats_sdk.internal.runtime import (
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
