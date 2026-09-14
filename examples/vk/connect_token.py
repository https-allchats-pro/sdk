"""VK: connect with a user access token.

    export VK_ACCESS_TOKEN=vk1.a.…
    python examples/vk/connect_token.py
"""

from __future__ import annotations

import asyncio
import os

from allchats_sdk import FileCredentialStore
from allchats_sdk.vk import VKClient


async def main() -> None:
    token = (os.environ.get("VK_ACCESS_TOKEN") or "").strip()
    if not token:
        raise SystemExit("Set VK_ACCESS_TOKEN")

    store = FileCredentialStore(os.environ.get("VK_SESSION_FILE", "./vk-session.json"))
    client = VKClient(
        account_id=os.environ.get("VK_ACCOUNT_ID", "acc-1"),
        app_id=os.environ.get("VK_APP_ID", ""),
        credential_store=store,
    )

    await client.auth.connect_with_token(token)
    status = await client.connect()
    print(f"connected user_id={status.user_id} state={status.state.value}")
    print(f"session saved → {store.path}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
