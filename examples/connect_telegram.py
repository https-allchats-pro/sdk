"""Connect a Telegram account via QR (or reconnect with saved session).

Requires ``[telegram]`` extra and Telegram API credentials from
https://my.telegram.org/apps

Run from the allchats-sdk directory:

    pip install -e ".[telegram]"
    export TELEGRAM_APP_ID=12345
    export TELEGRAM_APP_HASH=your_app_hash
    python examples/connect_telegram.py

Optional:

    export TELEGRAM_ACCOUNT_ID=acc-1
    export TELEGRAM_SESSION_FILE=./telegram-session.json
    # reconnect without QR if session file already has session_data:
    python examples/connect_telegram.py --reconnect
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any


@dataclass
class SavingEventSink:
    """Minimal EventSink that keeps the latest credentials in memory."""

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


def _load_settings() -> SimpleNamespace:
    app_id = int(os.environ.get("TELEGRAM_APP_ID") or "0")
    app_hash = (os.environ.get("TELEGRAM_APP_HASH") or "").strip()
    if not app_id or not app_hash:
        raise SystemExit("Set TELEGRAM_APP_ID and TELEGRAM_APP_HASH")
    return SimpleNamespace(telegram=SimpleNamespace(app_id=app_id, app_hash=app_hash, proxy=None))


def _session_path() -> Path:
    return Path(os.environ.get("TELEGRAM_SESSION_FILE") or "./telegram-session.json")


def _load_credentials(path: Path, account_id: str) -> dict[str, Any]:
    from allchats_sdk.credentials import new_telegram_credentials

    if not path.exists():
        return new_telegram_credentials(account_id=account_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return new_telegram_credentials(account_id=account_id)
    data.setdefault("device_id", account_id)
    return data


def _save_credentials(path: Path, credentials: dict[str, Any]) -> None:
    path.write_text(json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[telegram] saved session → {path}")


async def _wait_authorized(manager: Any, account_id: str, *, timeout_sec: float = 300.0) -> Any:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        client = manager.client_for_account(account_id)
        if client is None:
            await asyncio.sleep(0.5)
            continue
        if client.state_instance == "passwordRequired":
            password = await asyncio.to_thread(input, "Telegram 2FA password: ")
            await manager.submit_password(account_id, password.strip())
            print("[telegram] password submitted, waiting…")
        if client.state_instance == "authorized" or client.is_authorized:
            return client
        if client.state_instance == "error":
            raise RuntimeError(client.error or "telegram auth failed")
        await asyncio.sleep(0.5)
    raise TimeoutError("telegram authorization timed out")


async def connect_via_qr(account_id: str, session_file: Path) -> None:
    from allchats_sdk import MessengerClient
    from allchats_sdk.providers.register import register_builtin_providers
    from allchats_sdk.registry import default_registry

    register_builtin_providers()
    settings = _load_settings()
    sink = SavingEventSink()
    manager = default_registry.create("telegram", settings=settings, event_sink=sink)
    client = MessengerClient.from_provider("telegram", account_id, manager)

    credentials = _load_credentials(session_file, account_id)
    qr = await client.auth.start_qr(credentials)
    payload = manager.to_qr_response(qr)
    print("Scan this QR link in Telegram → Settings → Devices → Link Desktop Device:")
    print(payload["qr_link"])
    print(f"(expires_at={payload.get('expires_at')}, poll every {payload.get('polling_interval')} ms)")

    authorized = await _wait_authorized(manager, account_id)
    print(f"[telegram] authorized user_id={authorized.user_id}")

    saved = sink.credentials_by_account.get(account_id) or credentials
    if saved.get("session_data"):
        _save_credentials(session_file, saved)
    else:
        print("[telegram] warning: no session_data in EventSink yet; check CredentialsUpdatedEvent")

    # Keep the session worker briefly so reconnect path is clear.
    await asyncio.sleep(1)
    await manager.stop_session(account_id)
    await manager.stop_qr(account_id)


async def reconnect(account_id: str, session_file: Path) -> None:
    from allchats_sdk import MessengerClient
    from allchats_sdk.credentials import telegram_authorized
    from allchats_sdk.providers.register import register_builtin_providers
    from allchats_sdk.registry import default_registry

    register_builtin_providers()
    settings = _load_settings()
    sink = SavingEventSink()
    manager = default_registry.create("telegram", settings=settings, event_sink=sink)
    client = MessengerClient.from_provider("telegram", account_id, manager)

    credentials = _load_credentials(session_file, account_id)
    if not telegram_authorized(credentials):
        raise SystemExit(f"No authorized session in {session_file}; run without --reconnect first")

    state = await client.connect(credentials)
    print(f"[telegram] reconnected state={state.state_instance} user_id={state.user_id}")
    await asyncio.sleep(1)
    await manager.stop_session(account_id)


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
