"""Typed public provider facades (re-exports).

Prefer::

    from allchats_sdk import TelegramProvider, VKProvider, MAXProvider
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "MAXProvider",
    "TelegramProvider",
    "VKProvider",
]


def __getattr__(name: str) -> Any:
    if name == "TelegramProvider":
        from allchats_sdk.providers.telegram.provider import TelegramProvider

        return TelegramProvider
    if name == "VKProvider":
        from allchats_sdk.providers.vk.provider import VKProvider

        return VKProvider
    if name == "MAXProvider":
        from allchats_sdk.providers.max.provider import MAXProvider

        return MAXProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
