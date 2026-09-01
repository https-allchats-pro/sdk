"""Host ports — implemented by the application (backend), not by providers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MediaStorage(Protocol):
    """Persist downloaded messenger media files."""

    def save_voice(self, *, account_id: str, data: bytes, extension: str) -> str: ...

    def save_media(self, *, account_id: str, data: bytes, extension: str) -> str: ...

    def save_avatar(self, *, account_id: str, external_chat_id: str, data: bytes) -> str: ...


@runtime_checkable
class DeliveryTracker(Protocol):
    """Track outgoing message delivery/read receipts."""

    async def mark_up_to_external_id(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        max_external_id: int,
        status: str,
    ) -> None: ...

    async def mark_by_external_ids(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        external_ids: list[str],
        status: str,
    ) -> None: ...

    async def mark_up_to_sent_at(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        sent_before: datetime | int,
        status: str,
    ) -> None: ...


class IncomingMessageHandler(Protocol):
    """Host handler for rich incoming/outgoing media messages.

    Implemented by the backend (e.g. VoiceMessageService). Providers call
    these methods when media/voice processing must happen before persistence.
    """

    async def process_telegram_incoming(self, **kwargs: Any) -> bool: ...

    async def process_telegram_outgoing(self, **kwargs: Any) -> Any | None: ...

    async def process_vk_incoming(self, **kwargs: Any) -> bool: ...

    async def process_vk_outgoing(self, **kwargs: Any) -> Any | None: ...

    async def process_whatsapp_incoming(self, **kwargs: Any) -> bool: ...

    async def process_whatsapp_outgoing(self, **kwargs: Any) -> Any | None: ...

    async def process_max_incoming(self, **kwargs: Any) -> Any | None: ...

    async def process_max_outgoing(self, **kwargs: Any) -> Any | None: ...


@runtime_checkable
class CredentialStorage(Protocol):
    """Optional persistent credential store (backend implements)."""

    async def get(self, account_id: str) -> dict[str, Any] | None: ...

    async def save(self, account_id: str, credentials: dict[str, Any]) -> None: ...

    async def clear(self, account_id: str) -> None: ...
