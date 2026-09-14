"""VK: VK ID OAuth (PKCE).

    export VK_APP_ID=… VK_APP_SECRET=… VK_REDIRECT_URI=https://…
    python examples/vk/connect_oauth.py
"""

from __future__ import annotations

import asyncio
import os

from allchats_sdk import FileCredentialStore
from allchats_sdk.vk import VKClient


async def main() -> None:
    app_id = (os.environ.get("VK_APP_ID") or "").strip()
    app_secret = (os.environ.get("VK_APP_SECRET") or "").strip()
    redirect_uri = (os.environ.get("VK_REDIRECT_URI") or "").strip()
    if not (app_id and app_secret and redirect_uri):
        raise SystemExit("Set VK_APP_ID, VK_APP_SECRET and VK_REDIRECT_URI")

    store = FileCredentialStore(os.environ.get("VK_SESSION_FILE", "./vk-session.json"))
    client = VKClient(
        account_id=os.environ.get("VK_ACCOUNT_ID", "acc-1"),
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
        scopes=os.environ.get("VK_SCOPES", ""),
        credential_store=store,
    )

    print("Open this URL, authorize, then paste callback query values:")
    print(client.auth.build_oauth_url())
    print()

    code = input("code: ").strip()
    state = input("state: ").strip()
    device_id = input("device_id: ").strip()
    if not (code and state and device_id):
        raise SystemExit("code, state and device_id are required")

    await client.auth.connect_with_oauth_code(
        code=code,
        oauth_state=state,
        device_id=device_id,
    )
    status = await client.connect()
    print(f"authorized user_id={status.user_id} state={status.state.value}")
    print(f"session saved → {store.path}")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
