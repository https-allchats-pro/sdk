import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from allchats_sdk.protocols import SessionManager, SessionRuntime


class WebSmsCodeProvider:
    def __init__(self, runtime: "SessionRuntime", manager: "SessionManager") -> None:
        self._runtime = runtime
        self._manager = manager
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def get_code(self, phone: str) -> str:
        await self._manager.set_status(self._runtime.snapshot.session_id, "waiting_sms")
        return await self._queue.get()

    async def submit_code(self, code: str) -> None:
        await self._queue.put(code.strip())


class WebPasswordProvider:
    def __init__(self, runtime: "SessionRuntime", manager: "SessionManager") -> None:
        self._runtime = runtime
        self._manager = manager
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    async def get_password(self, hint: str | None = None) -> str:
        self._runtime.snapshot.password_hint = hint
        await self._manager.set_status(self._runtime.snapshot.session_id, "waiting_password")
        return await self._queue.get()

    async def submit_password(self, password: str) -> None:
        await self._queue.put(password)


class WebQrHandler:
    def __init__(self, runtime: "SessionRuntime", manager: "SessionManager") -> None:
        self._runtime = runtime
        self._manager = manager

    async def show_qr(self, qr_url: str) -> None:
        await self._manager.set_qr_url(self._runtime.snapshot.session_id, qr_url)
