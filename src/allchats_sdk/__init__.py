"""allchats-sdk — messenger integrations without application domain coupling."""

from allchats_sdk.protocols import (
    CredentialStorage,
    DeliveryTracker,
    EventSink,
    IncomingMessageHandler,
    MediaStorage,
    MessengerProvider,
    NullEventSink,
)
from allchats_sdk.registry import ProviderRegistry, default_registry

__all__ = [
    "CredentialStorage",
    "DeliveryTracker",
    "EventSink",
    "IncomingMessageHandler",
    "MediaStorage",
    "MessengerProvider",
    "NullEventSink",
    "ProviderRegistry",
    "default_registry",
    "__version__",
]

__version__ = "0.1.0"
