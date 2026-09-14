"""Telegram: stay online and print incoming messages.

Pass a small ``event_sink`` — the session is still persisted via ``credential_store``.

    export TELEGRAM_APP_ID=… TELEGRAM_APP_HASH=…
    python examples/telegram/receive_messages.py
"""

from __future__ import annotations

import asyncio
import os

from allchats_sdk import FileCredentialStore
from allchats_sdk.telegram import TelegramClient


class PrintIncoming:
    """Minimal EventSink: print inbound text, ignore the rest."""

    async def on_incoming(self, event) -> None:
        print(f"[{event.provider}] {event.external_chat_id} ← {event.from_id}: {event.text}")

    async def on_outgoing(self, event) -> None:
        return None

    async def on_credentials_updated(self, event) -> None:
        return None

    async def on_connection_state(self, event) -> None:
        print(f"state={event.state} error={event.error or '-'}")

    async def on_chats_discovered(self, event) -> None:
        print(f"chats discovered: {len(event.chats)}")

    async def on_chat_id_remap(self, event) -> None:
        return None


async def main() -> None:
    store = FileCredentialStore(os.environ.get("TELEGRAM_SESSION_FILE", "./telegram-session.json"))
    client = TelegramClient(
        account_id=os.environ.get("TELEGRAM_ACCOUNT_ID", "acc-1"),
        app_id=int(os.environ["TELEGRAM_APP_ID"]),
        app_hash=os.environ["TELEGRAM_APP_HASH"],
        credential_store=store,
        event_sink=PrintIncoming(),
    )

    status = await client.connect()
    if not status.is_authorized:
        raise SystemExit(f"not authorized ({status.state.value}); run connect_qr.py first")

    print(f"listening as user_id={status.user_id} — Ctrl+C to stop")
    try:
        await asyncio.Future()  # run forever
    except asyncio.CancelledError:
        pass
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
