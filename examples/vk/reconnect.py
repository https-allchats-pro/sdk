"""VK: reconnect using a saved session file.

    python examples/vk/reconnect.py
"""

from __future__ import annotations

import asyncio
import os

from allchats_sdk import FileCredentialStore
from allchats_sdk.vk import VKClient


async def main() -> None:
    store = FileCredentialStore(os.environ.get("VK_SESSION_FILE", "./vk-session.json"))
    client = VKClient(
        account_id=os.environ.get("VK_ACCOUNT_ID", "acc-1"),
        app_id=os.environ.get("VK_APP_ID", ""),
        credential_store=store,
    )

    status = await client.connect()
    print(f"reconnected user_id={status.user_id} state={status.state.value}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
