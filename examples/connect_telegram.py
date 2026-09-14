"""Connect a Telegram account via QR (or reconnect with saved session).

Preferred public API::

    store = FileCredentialStore("./telegram-session.json")
    client = TelegramClient(..., credential_store=store)
    await client.auth.start_qr()
    status = await client.auth.wait_until_authorized(
        password_provider=lambda: input("Telegram 2FA password: "),
    )

Requires ``[telegram]`` extra and credentials from https://my.telegram.org/apps

    pip install -e ".[telegram]"
    export TELEGRAM_APP_ID=12345
    export TELEGRAM_APP_HASH=your_app_hash
    python examples/connect_telegram.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from allchats_sdk import FileCredentialStore, TelegramClient


def _session_path() -> Path:
    return Path(os.environ.get("TELEGRAM_SESSION_FILE") or "./telegram-session.json")


def _build_client(account_id: str, store: FileCredentialStore) -> TelegramClient:
    app_id = int(os.environ.get("TELEGRAM_APP_ID") or "0")
    app_hash = (os.environ.get("TELEGRAM_APP_HASH") or "").strip()
    if not app_id or not app_hash:
        raise SystemExit("Set TELEGRAM_APP_ID and TELEGRAM_APP_HASH")
    return TelegramClient(
        account_id,
        app_id=app_id,
        app_hash=app_hash,
        credential_store=store,
    )


async def connect_via_qr(account_id: str, session_file: Path) -> None:
    store = FileCredentialStore(session_file)
    client = _build_client(account_id, store)
    assert client.auth is not None

    qr = await client.auth.start_qr()
    qr_link = getattr(qr, "qr_link", None) or getattr(qr, "auth_url", "") or ""
    print("Scan this QR link in Telegram → Settings → Devices → Link Desktop Device:")
    print(qr_link)

    authorized = await client.auth.wait_until_authorized(
        password_provider=lambda: input("Telegram 2FA password: "),
    )
    print(f"[telegram] authorized user_id={authorized.user_id} state={authorized.state.value}")
    print(f"[telegram] session saved → {store.path}")

    await asyncio.sleep(1)
    await client.disconnect()


async def reconnect(account_id: str, session_file: Path) -> None:
    store = FileCredentialStore(session_file)
    client = _build_client(account_id, store)
    status = await client.connect()
    print(f"[telegram] reconnected state={status.state.value} user_id={status.user_id}")
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
