"""allchats-sdk — messenger integrations without application domain coupling."""

from allchats_sdk.protocols import EventSink, MessengerProvider, NullEventSink
from allchats_sdk.registry import ProviderRegistry, default_registry

__all__ = [
    "EventSink",
    "MessengerProvider",
    "NullEventSink",
    "ProviderRegistry",
    "default_registry",
    "__version__",
]

__version__ = "0.1.0"
