"""Telegram: reconnect and send a text message.

    export TELEGRAM_APP_ID=… TELEGRAM_APP_HASH=…
    export TELEGRAM_CHAT_ID=123456789
    python examples/telegram/send_message.py
    # or: python examples/telegram/send_message.py "hello"
"""

from __future__ import annotations

import asyncio
import os
import sys

from allchats_sdk import FileCredentialStore
from allchats_sdk.telegram import TelegramClient


async def main() -> None:
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not chat_id:
        raise SystemExit("Set TELEGRAM_CHAT_ID (user/chat id as string)")

    text = " ".join(sys.argv[1:]).strip() or "hello from allchats-sdk"

    store = FileCredentialStore(os.environ.get("TELEGRAM_SESSION_FILE", "./telegram-session.json"))
    client = TelegramClient(
        account_id=os.environ.get("TELEGRAM_ACCOUNT_ID", "acc-1"),
        app_id=int(os.environ["TELEGRAM_APP_ID"]),
        app_hash=os.environ["TELEGRAM_APP_HASH"],
        credential_store=store,
    )

    status = await client.connect()
    if not status.is_authorized:
        raise SystemExit(f"not authorized ({status.state.value}); run connect_qr.py first")

    message_id, external_chat_id = await client.messages.send(text, chat_id=chat_id)
    print(f"sent message_id={message_id} chat_id={external_chat_id}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
