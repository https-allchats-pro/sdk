"""Messenger SDK errors (backend-agnostic)."""


class AllChatsError(Exception):
    """Base public exception for allchats-sdk."""


#: Backward-compatible alias for :class:`AllChatsError`.
MessengerError = AllChatsError


class ValidationError(AllChatsError):
    pass


class MessengerClientUnavailableError(AllChatsError):
    pass


class SessionNotConnectedError(AllChatsError):
    def __init__(self, status: str) -> None:
        super().__init__(f"Session is not connected: {status}")
        self.status = status


class UnsupportedCapabilityError(AllChatsError):
    def __init__(self, provider: str, capability: str) -> None:
        super().__init__(f"provider '{provider}' does not support '{capability}'")
        self.provider = provider
        self.capability = capability


def is_telegram_rpc_error(exc: BaseException) -> bool:
    try:
        from telethon.errors import RPCError
    except ImportError:
        return False
    return isinstance(exc, RPCError)
