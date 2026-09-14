"""Public MAX entrypoints.

Preferred after install::

    from allchats_sdk.max import MAXClient
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "MAXClient",
    "MAXProvider",
]


def __getattr__(name: str) -> Any:
    if name == "MAXClient":
        from allchats_sdk.clients.max import MAXClient

        return MAXClient
    if name == "MAXProvider":
        from allchats_sdk.providers.max.provider import MAXProvider

        return MAXProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
