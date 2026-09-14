"""Deprecated compatibility shim.

Use ``allchats_sdk.providers.telegram.provider`` (``TelegramProvider``).
"""

from __future__ import annotations

from allchats_sdk.providers.telegram.client import TelegramAccountClient
from allchats_sdk.providers.telegram.provider import TelegramClientManager, TelegramProvider

__all__ = [
    "TelegramAccountClient",
    "TelegramClientManager",
    "TelegramProvider",
]
