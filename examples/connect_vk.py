"""Connect a VK account (QR, OAuth, or user access_token).

Requires ``[vk]`` extra. Create an app at https://dev.vk.com/

Run from the allchats-sdk directory:

    pip install -e ".[vk]"

Modes:

1) QR (no OAuth redirect needed):

    export VK_APP_ID=12345678   # optional for QR; required for login/OAuth
    python examples/connect_vk.py --mode qr

2) User token (simplest for scripts):

    export VK_ACCESS_TOKEN=vk1.a....
    python examples/connect_vk.py --mode token

3) VK ID OAuth (PKCE, interactive — same process keeps code_verifier):

    export VK_APP_ID=12345678
    export VK_APP_SECRET=your_secret
    export VK_REDIRECT_URI=http://127.0.0.1:8090/vk/oauth/callback
    python examples/connect_vk.py --mode oauth

Optional:

    export VK_ACCOUNT_ID=acc-vk-1
    export VK_SESSION_FILE=./vk-session.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any


@dataclass
class SavingEventSink:
    credentials_by_account: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def on_incoming(self, event: Any) -> None:
        return None

    async def on_outgoing(self, event: Any) -> None:
        return None

    async def on_credentials_updated(self, event: Any) -> None:
        if event.clear:
            self.credentials_by_account.pop(event.connection_id, None)
            print(f"[vk] credentials cleared for {event.connection_id}")
            return
        self.credentials_by_account[event.connection_id] = dict(event.credentials or {})
        print(
            f"[vk] credentials updated account={event.connection_id} "
            f"user_id={event.user_id or event.credentials.get('user_id', '')}"
        )

    async def on_connection_state(self, event: Any) -> None:
        print(f"[vk] state={event.state} account={event.connection_id} error={event.error!r}")

    async def on_chats_discovered(self, event: Any) -> None:
        print(f"[vk] chats discovered: {len(event.chats)}")

    async def on_chat_id_remap(self, event: Any) -> None:
        return None


def _session_path() -> Path:
    return Path(os.environ.get("VK_SESSION_FILE") or "./vk-session.json")


def _load_settings(*, require_oauth: bool = False) -> SimpleNamespace:
    app_id = (os.environ.get("VK_APP_ID") or "").strip()
    app_secret = (os.environ.get("VK_APP_SECRET") or "").strip()
    redirect_uri = (os.environ.get("VK_REDIRECT_URI") or "").strip()
    scopes = (os.environ.get("VK_SCOPES") or "").strip()
    if require_oauth and not (app_id and app_secret and redirect_uri):
        raise SystemExit("Set VK_APP_ID, VK_APP_SECRET and VK_REDIRECT_URI for OAuth")
    return SimpleNamespace(
        vk=SimpleNamespace(
            app_id=app_id,
            app_secret=app_secret,
            redirect_uri=redirect_uri,
            scopes=scopes,
            is_configured=lambda: bool(app_id and app_secret and redirect_uri),
            login_auth_configured=lambda: bool(app_id),
        )
    )


def _save_credentials(path: Path, credentials: dict[str, Any]) -> None:
    path.write_text(json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[vk] saved session → {path}")


def _load_credentials(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


async def _wait_authorized(manager: Any, account_id: str, *, timeout_sec: float = 300.0) -> Any:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        client = manager.client_for_account(account_id)
        if client is None:
            await asyncio.sleep(0.5)
            continue
        if client.state_instance == "authorized" or client.is_authorized:
            return client
        if client.state_instance in {"notAuthorized", "error"} and client.error:
            raise RuntimeError(client.error)
        await asyncio.sleep(0.5)
    raise TimeoutError("vk authorization timed out")


def _build_manager(settings: SimpleNamespace, sink: SavingEventSink) -> Any:
    from allchats_sdk.providers.register import register_builtin_providers
    from allchats_sdk.registry import default_registry

    register_builtin_providers()
    return default_registry.create("vk", settings=settings, event_sink=sink)


async def connect_qr(account_id: str, session_file: Path) -> None:
    from allchats_sdk import MessengerClient

    settings = _load_settings()
    sink = SavingEventSink()
    manager = _build_manager(settings, sink)
    client = MessengerClient.from_provider("vk", account_id, manager)

    # VK start_qr does not take credentials; MessengerClient falls back via TypeError.
    qr = await client.auth.start_qr()
    payload = manager.to_qr_response(qr)
    print("Open VK on your phone → Profile → QR scanner and scan:")
    print(payload["qr_link"])

    authorized = await _wait_authorized(manager, account_id)
    print(f"[vk] authorized user_id={authorized.user_id}")

    saved = sink.credentials_by_account.get(account_id)
    if saved:
        _save_credentials(session_file, saved)

    await asyncio.sleep(1)
    await client.disconnect()


async def connect_token(account_id: str, session_file: Path) -> None:
    from allchats_sdk import MessengerClient

    access_token = (os.environ.get("VK_ACCESS_TOKEN") or "").strip()
    if not access_token:
        raise SystemExit("Set VK_ACCESS_TOKEN")

    settings = _load_settings()
    sink = SavingEventSink()
    manager = _build_manager(settings, sink)

    credentials = await manager.connect_with_token(account_id, access_token=access_token)
    _save_credentials(session_file, credentials)

    client = MessengerClient.from_provider("vk", account_id, manager)
    state = await client.connect(credentials)
    print(f"[vk] connected state={state.state_instance} user_id={state.user_id}")
    await asyncio.sleep(1)
    await client.disconnect()


async def connect_oauth(account_id: str, session_file: Path) -> None:
    """Interactive OAuth: PKCE verifier must stay on the same manager instance."""
    from allchats_sdk import MessengerClient

    settings = _load_settings(require_oauth=True)
    sink = SavingEventSink()
    manager = _build_manager(settings, sink)

    url = manager.build_oauth_authorization_url(account_id)
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

    mapped = manager.resolve_oauth_account_id(state)
    target_account = mapped or account_id
    credentials = await manager.connect_with_oauth_code(
        target_account,
        code=code,
        oauth_state=state,
        device_id=device_id,
    )
    _save_credentials(session_file, credentials)

    client = MessengerClient.from_provider("vk", target_account, manager)
    state_client = await client.connect(credentials)
    print(f"[vk] oauth connected state={state_client.state_instance} user_id={state_client.user_id}")
    await asyncio.sleep(1)
    await client.disconnect()


async def reconnect(account_id: str, session_file: Path) -> None:
    from allchats_sdk import MessengerClient
    from allchats_sdk.credentials import vk_authorized

    credentials = _load_credentials(session_file)
    if not vk_authorized(credentials):
        raise SystemExit(f"No authorized session in {session_file}")

    settings = _load_settings()
    sink = SavingEventSink()
    manager = _build_manager(settings, sink)
    client = MessengerClient.from_provider("vk", account_id, manager)
    state = await client.connect(credentials)
    print(f"[vk] reconnected state={state.state_instance} user_id={state.user_id}")
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
