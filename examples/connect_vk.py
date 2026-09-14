"""Connect a VK account (QR, OAuth, or user access_token).

Preferred public API::

    store = FileCredentialStore("./vk-session.json")
    client = VKClient(account_id=..., app_id=..., credential_store=store)

Requires ``[vk]`` extra. Create an app at https://dev.vk.com/

    pip install -e ".[vk]"
    python examples/connect_vk.py --mode qr
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from allchats_sdk import AllChatsError, ConnectionState, FileCredentialStore, VKClient


def _session_path() -> Path:
    return Path(os.environ.get("VK_SESSION_FILE") or "./vk-session.json")


def _connection_state(account_id: str, raw: object) -> ConnectionState:
    return ConnectionState(
        connection_id=account_id,
        state=str(getattr(raw, "state_instance", "") or "unknown"),
        user_id=str(getattr(raw, "user_id", "") or ""),
        error=str(getattr(raw, "error", "") or ""),
    )


def _build_client(
    account_id: str,
    store: FileCredentialStore,
    *,
    require_oauth: bool = False,
) -> VKClient:
    app_id = (os.environ.get("VK_APP_ID") or "").strip()
    app_secret = (os.environ.get("VK_APP_SECRET") or "").strip()
    redirect_uri = (os.environ.get("VK_REDIRECT_URI") or "").strip()
    scopes = (os.environ.get("VK_SCOPES") or "").strip()
    if require_oauth and not (app_id and app_secret and redirect_uri):
        raise SystemExit("Set VK_APP_ID, VK_APP_SECRET and VK_REDIRECT_URI for OAuth")
    return VKClient(
        account_id,
        app_id=app_id,
        app_secret=app_secret,
        redirect_uri=redirect_uri,
        scopes=scopes,
        credential_store=store,
    )


async def _wait_authorized(client: VKClient, *, timeout_sec: float = 300.0) -> ConnectionState:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        raw = await client.chats.client_state()
        if raw is None:
            await asyncio.sleep(0.5)
            continue
        status = _connection_state(client.account_id, raw)
        if status.state == "authorized" or bool(status.user_id):
            return status
        if status.state in {"notAuthorized", "error"} and status.error:
            raise AllChatsError(status.error)
        await asyncio.sleep(0.5)
    raise TimeoutError("vk authorization timed out")


async def connect_qr(account_id: str, session_file: Path) -> None:
    store = FileCredentialStore(session_file)
    client = _build_client(account_id, store)
    assert client.auth is not None

    qr = await client.auth.start_qr()
    qr_link = getattr(qr, "auth_url", None) or getattr(qr, "qr_link", "") or ""
    print("Open VK on your phone → Profile → QR scanner and scan:")
    print(qr_link)

    authorized = await _wait_authorized(client)
    print(f"[vk] authorized user_id={authorized.user_id} state={authorized.state}")
    print(f"[vk] session saved → {store.path}")

    await asyncio.sleep(1)
    await client.disconnect()


async def connect_token(account_id: str, session_file: Path) -> None:
    access_token = (os.environ.get("VK_ACCESS_TOKEN") or "").strip()
    if not access_token:
        raise SystemExit("Set VK_ACCESS_TOKEN")

    store = FileCredentialStore(session_file)
    client = _build_client(account_id, store)
    assert client.auth is not None

    await client.auth.connect_with_token(access_token)
    raw = await client.connect()
    status = _connection_state(account_id, raw)
    print(f"[vk] connected state={status.state} user_id={status.user_id}")
    print(f"[vk] session saved → {store.path}")
    await asyncio.sleep(1)
    await client.disconnect()


async def connect_oauth(account_id: str, session_file: Path) -> None:
    store = FileCredentialStore(session_file)
    client = _build_client(account_id, store, require_oauth=True)
    assert client.auth is not None

    url = client.auth.build_oauth_url()
    print("Open this URL in a browser and authorize the app:")
    print(url)
    print()
    print("After redirect, paste query values from the callback URL.")
    print("(VK ID usually returns code, state, and device_id.)")
    code = (await asyncio.to_thread(input, "code: ")).strip()
    state = (await asyncio.to_thread(input, "state: ")).strip()
    device_id = (await asyncio.to_thread(input, "device_id: ")).strip()
    if not code or not state or not device_id:
        raise SystemExit("code, state and device_id are required")

    await client.auth.connect_with_oauth_code(
        code=code,
        oauth_state=state,
        device_id=device_id,
    )
    raw = await client.connect()
    status = _connection_state(account_id, raw)
    print(f"[vk] oauth connected state={status.state} user_id={status.user_id}")
    print(f"[vk] session saved → {store.path}")
    await asyncio.sleep(1)
    await client.disconnect()


async def reconnect(account_id: str, session_file: Path) -> None:
    store = FileCredentialStore(session_file)
    client = _build_client(account_id, store)
    raw = await client.connect()
    status = _connection_state(account_id, raw)
    print(f"[vk] reconnected state={status.state} user_id={status.user_id}")
    await asyncio.sleep(1)
    await client.disconnect()


async def main() -> None:
    parser = argparse.ArgumentParser(description="VK connect examples")
    parser.add_argument(
        "--mode",
        choices=("qr", "token", "oauth", "reconnect"),
        default="qr",
    )
    args = parser.parse_args()

    account_id = (os.environ.get("VK_ACCOUNT_ID") or "acc-vk-1").strip()
    session_file = _session_path()

    if args.mode == "qr":
        await connect_qr(account_id, session_file)
    elif args.mode == "token":
        await connect_token(account_id, session_file)
    elif args.mode == "oauth":
        await connect_oauth(account_id, session_file)
    else:
        await reconnect(account_id, session_file)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
