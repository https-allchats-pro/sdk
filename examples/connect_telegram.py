"""Connect a Telegram account via QR (or reconnect with saved session).

Preferred public API — account client only::

    client = TelegramClient(account_id=..., app_id=..., app_hash=...)

Requires ``[telegram]`` extra and credentials from https://my.telegram.org/apps

    pip install -e ".[telegram]"
    export TELEGRAM_APP_ID=12345
    export TELEGRAM_APP_HASH=your_app_hash
    python examples/connect_telegram.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from allchats_sdk import AllChatsError, ConnectionState, TelegramClient


@dataclass
class SavingEventSink:
    """Minimal host EventSink that keeps the latest credentials in memory."""

    credentials_by_account: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def on_incoming(self, event: Any) -> None:
        return None

    async def on_outgoing(self, event: Any) -> None:
        return None

    async def on_credentials_updated(self, event: Any) -> None:
        if event.clear:
            self.credentials_by_account.pop(event.connection_id, None)
            print(f"[telegram] credentials cleared for {event.connection_id}")
            return
        self.credentials_by_account[event.connection_id] = dict(event.credentials or {})
        print(
            f"[telegram] credentials updated account={event.connection_id} "
            f"user_id={event.user_id or event.credentials.get('user_id', '')}"
        )

    async def on_connection_state(self, event: Any) -> None:
        print(f"[telegram] state={event.state} account={event.connection_id} error={event.error!r}")

    async def on_chats_discovered(self, event: Any) -> None:
        print(f"[telegram] chats discovered: {len(event.chats)}")

    async def on_chat_id_remap(self, event: Any) -> None:
        return None


def _session_path() -> Path:
    return Path(os.environ.get("TELEGRAM_SESSION_FILE") or "./telegram-session.json")


def _new_credentials(account_id: str) -> dict[str, Any]:
    return {"device_id": account_id, "user_id": "", "session_data": ""}


def _load_credentials(path: Path, account_id: str) -> dict[str, Any]:
    if not path.exists():
        return _new_credentials(account_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return _new_credentials(account_id)
    data.setdefault("device_id", account_id)
    return data


def _save_credentials(path: Path, credentials: dict[str, Any]) -> None:
    path.write_text(json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[telegram] saved session → {path}")


def _is_authorized(credentials: dict[str, Any]) -> bool:
    return bool(str(credentials.get("user_id") or "").strip()) or bool(
        str(credentials.get("session_data") or "").strip()
    )


def _connection_state(account_id: str, raw: Any) -> ConnectionState:
    return ConnectionState(
        connection_id=account_id,
        state=str(getattr(raw, "state_instance", "") or "unknown"),
        user_id=str(getattr(raw, "user_id", "") or ""),
        error=str(getattr(raw, "error", "") or ""),
    )


def _build_client(account_id: str, sink: SavingEventSink) -> TelegramClient:
    app_id = int(os.environ.get("TELEGRAM_APP_ID") or "0")
    app_hash = (os.environ.get("TELEGRAM_APP_HASH") or "").strip()
    if not app_id or not app_hash:
        raise SystemExit("Set TELEGRAM_APP_ID and TELEGRAM_APP_HASH")
    return TelegramClient(
        account_id,
        app_id=app_id,
        app_hash=app_hash,
        event_sink=sink,
    )


async def _wait_authorized(client: TelegramClient, *, timeout_sec: float = 300.0) -> ConnectionState:
    assert client.auth is not None
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        raw = await client.chats.client_state()
        if raw is None:
            await asyncio.sleep(0.5)
            continue
        status = _connection_state(client.account_id, raw)
        if status.state == "passwordRequired":
            password = await asyncio.to_thread(input, "Telegram 2FA password: ")
            await client.auth.submit_password(password.strip())
            print("[telegram] password submitted, waiting…")
        if status.state == "authorized" or bool(status.user_id):
            return status
        if status.state == "error":
            raise AllChatsError(status.error or "telegram auth failed")
        await asyncio.sleep(0.5)
    raise TimeoutError("telegram authorization timed out")


async def connect_via_qr(account_id: str, session_file: Path) -> None:
    sink = SavingEventSink()
    client = _build_client(account_id, sink)
    assert client.auth is not None

    credentials = _load_credentials(session_file, account_id)
    qr = await client.auth.start_qr(credentials)
    qr_link = getattr(qr, "qr_link", None) or getattr(qr, "auth_url", "") or ""
    print("Scan this QR link in Telegram → Settings → Devices → Link Desktop Device:")
    print(qr_link)

    authorized = await _wait_authorized(client)
    print(f"[telegram] authorized user_id={authorized.user_id} state={authorized.state}")

    saved = sink.credentials_by_account.get(account_id) or credentials
    if saved.get("session_data"):
        _save_credentials(session_file, saved)
    else:
        print("[telegram] warning: no session_data in EventSink yet")

    await asyncio.sleep(1)
    await client.disconnect()


async def reconnect(account_id: str, session_file: Path) -> None:
    sink = SavingEventSink()
    client = _build_client(account_id, sink)

    credentials = _load_credentials(session_file, account_id)
    if not _is_authorized(credentials):
        raise SystemExit(f"No authorized session in {session_file}; run without --reconnect first")

    raw = await client.connect(credentials)
    status = _connection_state(account_id, raw)
    print(f"[telegram] reconnected state={status.state} user_id={status.user_id}")
    await asyncio.sleep(1)
    await client.disconnect()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Telegram QR / reconnect example")
    parser.add_argument("--reconnect", action="store_true", help="reuse TELEGRAM_SESSION_FILE")
    args = parser.parse_args()

    account_id = (os.environ.get("TELEGRAM_ACCOUNT_ID") or "acc-telegram-1").strip()
    session_file = _session_path()

    if args.reconnect:
        await reconnect(account_id, session_file)
    else:
        await connect_via_qr(account_id, session_file)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
