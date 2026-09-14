"""MAX provider — host-owned session runtime bridge.

Conceptual API matches Telegram/VK providers (``connect_account``, ``start_qr``,
``disconnect``, ``send_message``). Implementation delegates to ``session_host``.
"""

from __future__ import annotations

from typing import Any

from allchats_sdk.errors import MessengerClientUnavailableError, UnsupportedCapabilityError

__all__ = ["MAXProvider"]


class MAXProvider:
    """Public MAX provider; sessions are owned by the host SessionManager."""

    provider_id = "max"

    def __init__(self, *, session_host: Any) -> None:
        if session_host is None:
            raise ValueError("session_host is required")
        self.session_host = session_host

    def client_for_account(self, account_id: str) -> Any | None:
        finder = getattr(self.session_host, "find_account_runtime", None)
        if finder is None:
            return None
        return finder(account_id)

    async def connect_account(
        self,
        account_id: str,
        credentials: dict[str, Any] | None = None,
    ) -> Any:
        _ = credentials
        return await self.session_host.connect_account(account_id)

    async def start_qr(
        self,
        account_id: str,
        credentials: dict[str, Any] | None = None,
        *,
        refresh: bool = False,
    ) -> Any:
        _ = refresh
        if credentials is None:
            raise ValueError("credentials are required for max QR auth")
        return await self.session_host.start_qr_for_account(account_id, credentials)

    async def stop_qr(self, account_id: str) -> None:
        _ = account_id
        return None

    async def disconnect(self, account_id: str) -> None:
        stop = getattr(self.session_host, "stop_account_sessions", None)
        if stop is None:
            raise UnsupportedCapabilityError("max", "auth.disconnect")
        await stop(account_id)

    async def stop_session(self, account_id: str) -> None:
        await self.disconnect(account_id)

    async def submit_password(self, account_id: str, password: str) -> None:
        submit = getattr(self.session_host, "submit_account_password", None)
        if submit is None:
            raise UnsupportedCapabilityError("max", "auth.submit_password")
        await submit(account_id, password)

    async def send_message(
        self,
        account_id: str,
        *,
        text: str,
        chat_id: str | None = None,
        phone_number: str | None = None,
        reply_to_external_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        runtime = self.client_for_account(account_id)
        if runtime is None:
            raise MessengerClientUnavailableError("max session is not connected")
        session_id = runtime.snapshot.session_id
        reply_to = _optional_int(reply_to_external_id)
        if phone_number:
            send_by_phone = getattr(self.session_host, "send_message_by_phone", None)
            if send_by_phone is None:
                raise UnsupportedCapabilityError("max", "messages.send_by_phone")
            return await send_by_phone(
                session_id,
                phone_number,
                text,
                reply_to=reply_to,
                **kwargs,
            )
        if chat_id is None:
            raise ValueError("chat_id or phone_number is required")
        return await self.session_host.send_message(
            session_id,
            int(chat_id),
            text,
            reply_to=reply_to,
            **kwargs,
        )


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return int(raw)
