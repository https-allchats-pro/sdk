"""Capability protocols for the MessengerClient facade."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MessageSender(Protocol):
    async def send(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        phone_number: str | None = None,
        reply_to_external_id: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str]: ...


@runtime_checkable
class ChatReader(Protocol):
    async def client_state(self) -> Any: ...

    async def sync(self) -> Any: ...


@runtime_checkable
class MessengerAuthenticator(Protocol):
    async def connect(self, credentials: dict[str, Any]) -> Any: ...

    async def start_qr(self, credentials: dict[str, Any] | None = None, **kwargs: Any) -> Any: ...

    async def disconnect(self) -> None: ...
