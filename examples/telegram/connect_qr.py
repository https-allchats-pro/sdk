"""Telegram: first-time login via QR.

Get app credentials at https://my.telegram.org/apps

    pip install -e ".[telegram]"
    export TELEGRAM_APP_ID=12345
    export TELEGRAM_APP_HASH=your_app_hash
    python examples/telegram/connect_qr.py
"""

from __future__ import annotations

import asyncio
import os

from allchats_sdk import FileCredentialStore
from allchats_sdk.telegram import TelegramClient


async def main() -> None:
    store = FileCredentialStore(os.environ.get("TELEGRAM_SESSION_FILE", "./telegram-session.json"))
    client = TelegramClient(
        account_id=os.environ.get("TELEGRAM_ACCOUNT_ID", "acc-1"),
        app_id=int(os.environ["TELEGRAM_APP_ID"]),
        app_hash=os.environ["TELEGRAM_APP_HASH"],
        credential_store=store,
    )

    qr = await client.auth.start_qr()
    print("Scan in Telegram → Settings → Devices → Link Desktop Device:")
    print(getattr(qr, "qr_link", None) or qr)

    status = await client.auth.wait_until_authorized(
        password_provider=lambda: input("2FA password (if asked): "),
    )
    print(f"authorized user_id={status.user_id} state={status.state.value}")
    print(f"session saved → {store.path}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
