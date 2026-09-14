"""allchats-sdk — messenger integrations without application domain coupling.

Public API (stable)
-------------------
Import from the package root::

    from allchats_sdk import (
        MessengerClient,
        Message,
        Chat,
        Account,
        ConnectionState,
        Capability,
        AllChatsError,
    )

Everything else (``registry``, ``host``, ``hooks``, ``providers.*``, …) is
**internal** unless documented otherwise. Prefer the root facade for new code.
"""

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
    "MaxMessengerClient",
    "Message",
    "MessengerClient",
    "__version__",
]

__version__ = "0.1.0"
