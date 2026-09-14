"""Telegram: reconnect using a saved session file.

Run ``connect_qr.py`` once first, then:

    export TELEGRAM_APP_ID=… TELEGRAM_APP_HASH=…
    python examples/telegram/reconnect.py
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

    # Loads credentials from the store automatically.
    status = await client.connect()
    print(f"reconnected user_id={status.user_id} state={status.state.value}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
