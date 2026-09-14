"""allchats-sdk — messenger integrations without application domain coupling.

Public API (stable)
-------------------
Import from the package root::

    from allchats_sdk import (
        MessengerClient,
        TelegramProvider,
        VKProvider,
        MAXProvider,
        Message,
        Chat,
        Account,
        ConnectionState,
        Capability,
        AllChatsError,
    )

    telegram = TelegramProvider(settings=settings, event_sink=sink)
    client = MessengerClient(provider=telegram, account_id=account_id)

The registry is an internal SDK mechanism, not the preferred usage path.
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
    "MAXProvider",
    "MaxMessengerClient",
    "Message",
    "MessengerClient",
    "TelegramProvider",
    "VKProvider",
    "__version__",
]

__version__ = "0.1.0"


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
