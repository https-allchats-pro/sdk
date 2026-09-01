"""Host ports implemented by the application (backend).

Prefer EventSink for message/session traffic. MaxSessionHost remains for the
MAX session-manager orchestration model.
"""

from __future__ import annotations

from typing import Any, Protocol

from allchats_sdk.protocols import EventSink, NullEventSink

__all__ = [
    "EventSink",
    "NullEventSink",
    "MaxSessionHost",
    "SessionManager",
    "SessionRuntime",
]


class MaxSessionHost(Protocol):
    async def set_status(self, session_id: str, status: str, **kwargs: Any) -> Any: ...

    async def set_qr_url(self, session_id: str, qr_url: str) -> Any: ...

    async def set_qr_info(self, *args: Any, **kwargs: Any) -> Any: ...

    async def update_qr_watcher(self, *args: Any, **kwargs: Any) -> Any: ...

    async def set_sms_token(self, session_id: str, token: str) -> Any: ...

    async def set_password_challenge(self, *args: Any, **kwargs: Any) -> Any: ...

    async def publish_message(self, *args: Any, **kwargs: Any) -> Any: ...

    async def notify_incoming_message(self, *args: Any, **kwargs: Any) -> Any: ...

    async def on_client_ready(self, session_id: str, client: Any) -> Any: ...


SessionManager = MaxSessionHost
SessionRuntime = Any
