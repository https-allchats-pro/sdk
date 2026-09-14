"""MAX: send a message through the host-backed client.

    export MAX_CHAT_ID=12345
    python examples/max/send_message.py "hello"
"""

from __future__ import annotations

import asyncio
import os
import sys


def get_session_host():
    raise SystemExit(
        "Wire get_session_host() to your SessionManager, then re-run.\n"
        "See examples/max/connect.py"
    )


async def main() -> None:
    from allchats_sdk.max import MAXClient

    chat_id = (os.environ.get("MAX_CHAT_ID") or "").strip()
    if not chat_id:
        raise SystemExit("Set MAX_CHAT_ID")
    text = " ".join(sys.argv[1:]).strip() or "hello from allchats-sdk"

    client = MAXClient(
        account_id=os.environ.get("MAX_ACCOUNT_ID", "acc-1"),
        session_host=get_session_host(),
    )

    await client.connect()
    result = await client.messages.send(text, chat_id=chat_id)
    print(f"sent → {result}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
