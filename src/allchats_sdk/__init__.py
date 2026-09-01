"""allchats-sdk — messenger integrations without application domain coupling."""

from allchats_sdk.capabilities import ChatReader, MessageSender, MessengerAuthenticator
from allchats_sdk.client import MaxMessengerClient, MessengerClient
from allchats_sdk.errors import (
    MessengerClientUnavailableError,
    MessengerError,
    SessionNotConnectedError,
    UnsupportedCapabilityError,
    ValidationError,
)
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
    "ChatReader",
    "CredentialStorage",
    "DeliveryTracker",
    "EventSink",
    "IncomingMessageHandler",
    "MaxMessengerClient",
    "MediaStorage",
    "MessageSender",
    "MessengerAuthenticator",
    "MessengerClient",
    "MessengerClientUnavailableError",
    "MessengerError",
    "MessengerProvider",
    "NullEventSink",
    "ProviderRegistry",
    "SessionNotConnectedError",
    "UnsupportedCapabilityError",
    "ValidationError",
    "default_registry",
    "__version__",
]

__version__ = "0.1.0"
