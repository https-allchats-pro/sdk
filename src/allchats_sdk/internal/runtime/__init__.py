"""Host-owned runtime bridges (MAX session manager, builtin registration).

Prefer ``allchats_sdk.protocols`` for EventSink / MaxSessionHost typing.
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
    "register_builtin_providers",
]


def __getattr__(name: str):
    if name == "register_builtin_providers":
        from allchats_sdk.internal.runtime.register import register_builtin_providers

        return register_builtin_providers
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
