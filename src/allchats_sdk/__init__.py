"""allchats-sdk — messenger integrations without application domain coupling.

Public API (stable)
-------------------
Preferred account clients::

    from allchats_sdk import TelegramClient

    client = TelegramClient(
        account_id="acc-1",
        app_id=12345,
        app_hash="...",
    )

Lower-level typed providers + ``MessengerClient`` remain available for hosts.
The registry is an internal SDK mechanism.
"""

from __future__ import annotations

from typing import Any

from allchats_sdk.client import MaxMessengerClient, MessengerClient
from allchats_sdk.errors import AllChatsError
from allchats_sdk.models import (
    Account,
    Capability,
    Chat,
    ConnectionState,
    Message,
)

__all__ = [
    "Account",
    "AllChatsError",
    "Capability",
    "Chat",
    "ConnectionState",
    "MAXClient",
    "MAXProvider",
    "MaxMessengerClient",
    "Message",
    "MessengerClient",
    "TelegramClient",
    "TelegramProvider",
    "VKClient",
    "VKProvider",
    "__version__",
]

__version__ = "0.1.0"


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
