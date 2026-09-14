"""Public Telegram entrypoints.

Preferred after install::

    from allchats_sdk.telegram import TelegramClient
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "TelegramClient",
    "TelegramProvider",
]


def __getattr__(name: str) -> Any:
    if name == "TelegramClient":
        from allchats_sdk.clients.telegram import TelegramClient

        return TelegramClient
    if name == "TelegramProvider":
        from allchats_sdk.providers.telegram.provider import TelegramProvider

        return TelegramProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
