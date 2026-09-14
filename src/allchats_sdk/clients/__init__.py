"""Account-level public clients (preferred API)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "MAXClient",
    "TelegramClient",
    "VKClient",
]


def __getattr__(name: str) -> Any:
    if name == "TelegramClient":
        from allchats_sdk.clients.telegram import TelegramClient

        return TelegramClient
    if name == "VKClient":
        from allchats_sdk.clients.vk import VKClient

        return VKClient
    if name == "MAXClient":
        from allchats_sdk.clients.max import MAXClient

        return MAXClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
