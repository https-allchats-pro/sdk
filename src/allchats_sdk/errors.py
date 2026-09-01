"""Messenger SDK errors (backend-agnostic)."""


class MessengerError(Exception):
    """Base SDK exception."""


class ValidationError(MessengerError):
    pass


class MessengerClientUnavailableError(MessengerError):
    pass


class SessionNotConnectedError(MessengerError):
    def __init__(self, status: str) -> None:
        super().__init__(f"Session is not connected: {status}")
        self.status = status


def is_telegram_rpc_error(exc: BaseException) -> bool:
    try:
        from telethon.errors import RPCError
    except ImportError:
        return False
    return isinstance(exc, RPCError)
