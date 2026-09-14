"""Deprecated compatibility shim.

Use ``allchats_sdk.protocols`` instead::

    from allchats_sdk.protocols import MediaStorage, EventSink, IncomingMessageHandler
"""

from __future__ import annotations

from allchats_sdk.protocols import (
    CredentialStorage,
    DeliveryTracker,
    IncomingMessageHandler,
    MediaStorage,
)

__all__ = [
    "CredentialStorage",
    "DeliveryTracker",
    "IncomingMessageHandler",
    "MediaStorage",
]
