"""Deprecated compatibility shim.

Use ``allchats_sdk.internal.observability`` instead.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "configure_metrics",
    "record_auth",
    "record_message",
]


def configure_metrics(**kwargs: Any) -> None:
    from allchats_sdk.internal import observability as _obs

    _obs.configure_metrics(**kwargs)


def __getattr__(name: str) -> Any:
    from allchats_sdk.internal import observability as _obs

    return getattr(_obs, name)
