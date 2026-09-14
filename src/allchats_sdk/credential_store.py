"""Public credential persistence for account clients."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CredentialStore(Protocol):
    """Persist messenger session credentials for an account."""

    async def get(self, account_id: str) -> dict[str, Any] | None: ...

    async def save(self, account_id: str, credentials: dict[str, Any]) -> None: ...

    async def clear(self, account_id: str) -> None: ...


class MemoryCredentialStore:
    """In-memory credential store (tests / ephemeral sessions)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    async def get(self, account_id: str) -> dict[str, Any] | None:
        payload = self._data.get(account_id)
        return dict(payload) if payload is not None else None

    async def save(self, account_id: str, credentials: dict[str, Any]) -> None:
        self._data[account_id] = dict(credentials or {})

    async def clear(self, account_id: str) -> None:
        self._data.pop(account_id, None)


class FileCredentialStore:
    """JSON file store for a single account session.

    Example::

        store = FileCredentialStore("./telegram-session.json")
        client = TelegramClient(..., credential_store=store)
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    async def get(self, account_id: str) -> dict[str, Any] | None:
        _ = account_id
        if not self._path.exists():
            return None
        raw = await _read_text(self._path)
        if not raw.strip():
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        return dict(data)

    async def save(self, account_id: str, credentials: dict[str, Any]) -> None:
        _ = account_id
        payload = dict(credentials or {})
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        await _write_text(self._path, text)

    async def clear(self, account_id: str) -> None:
        _ = account_id
        if self._path.exists():
            await _unlink(self._path)


async def _read_text(path: Path) -> str:
    import asyncio

    return await asyncio.to_thread(path.read_text, encoding="utf-8")


async def _write_text(path: Path, text: str) -> None:
    import asyncio

    def _write() -> None:
        path.write_text(text, encoding="utf-8")

    await asyncio.to_thread(_write)


async def _unlink(path: Path) -> None:
    import asyncio

    await asyncio.to_thread(path.unlink)
