"""Telegram: inspect which MessengerClient capability groups are available.

    pip install "allchats-sdk[telegram]"
    export TELEGRAM_APP_ID=… TELEGRAM_APP_HASH=…
    python examples/telegram/inspect_capabilities.py

Does not require a live session file — only constructs the client.
"""

from __future__ import annotations

import asyncio
import os

from allchats_sdk import Capability, FileCredentialStore
from allchats_sdk.errors import UnsupportedCapabilityError
from allchats_sdk.telegram import TelegramClient


async def main() -> None:
    print("Capability enum:", [c.value for c in Capability])

    store = FileCredentialStore(os.environ.get("TELEGRAM_SESSION_FILE", "./telegram-session.json"))
    client = TelegramClient(
        account_id=os.environ.get("TELEGRAM_ACCOUNT_ID", "acc-1"),
        app_id=int(os.environ["TELEGRAM_APP_ID"]),
        app_hash=os.environ["TELEGRAM_APP_HASH"],
        credential_store=store,
    )

    # There is no client.capabilities list — probe properties instead.
    print("auth:", "available" if client.auth is not None else "none")
    for name in ("messages", "chats"):
        try:
            attr = getattr(client, name)
            print(f"{name}: available → {type(attr).__name__}")
        except UnsupportedCapabilityError as exc:
            print(f"{name}: unsupported ({exc.capability})")


if __name__ == "__main__":
    asyncio.run(main())
