"""VK: reconnect and send a text message.

    export VK_CHAT_ID=123456789
    python examples/vk/send_message.py
    # or: python examples/vk/send_message.py "hello"
"""

from __future__ import annotations

import asyncio
import os
import sys

from allchats_sdk import FileCredentialStore
from allchats_sdk.vk import VKClient


async def main() -> None:
    chat_id = (os.environ.get("VK_CHAT_ID") or "").strip()
    if not chat_id:
        raise SystemExit("Set VK_CHAT_ID (peer id as string, e.g. user id)")

    text = " ".join(sys.argv[1:]).strip() or "hello from allchats-sdk"

    store = FileCredentialStore(os.environ.get("VK_SESSION_FILE", "./vk-session.json"))
    client = VKClient(
        account_id=os.environ.get("VK_ACCOUNT_ID", "acc-1"),
        app_id=os.environ.get("VK_APP_ID", ""),
        credential_store=store,
    )

    status = await client.connect()
    if not status.is_authorized:
        raise SystemExit(f"not authorized ({status.state.value}); run connect_qr.py or connect_token.py first")

    message_id, external_chat_id = await client.messages.send(text, chat_id=chat_id)
    print(f"sent message_id={message_id} chat_id={external_chat_id}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
