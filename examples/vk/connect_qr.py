"""VK: first-time login via QR.

Create an app at https://dev.vk.com/ (app_id helps login/QR features).

    pip install -e ".[vk]"
    export VK_APP_ID=12345678
    python examples/vk/connect_qr.py
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
        app_secret=os.environ.get("VK_APP_SECRET", ""),
        redirect_uri=os.environ.get("VK_REDIRECT_URI", ""),
        scopes=os.environ.get("VK_SCOPES", ""),
        credential_store=store,
    )

    qr = await client.auth.start_qr()
    print("Open VK → Profile → QR scanner and scan:")
    print(getattr(qr, "auth_url", None) or getattr(qr, "qr_link", None) or qr)

    status = await client.auth.wait_until_authorized()
    print(f"authorized user_id={status.user_id} state={status.state.value}")
    print(f"session saved → {store.path}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
