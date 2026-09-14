"""MAX: start QR auth for an account (host SessionManager required).

    # after wiring get_session_host() in this file (or import your host):
    python examples/max/connect_qr.py
"""

from __future__ import annotations

import asyncio
import os


def get_session_host():
    raise SystemExit(
        "Wire get_session_host() to your SessionManager, then re-run.\n"
        "See examples/max/connect.py"
    )


async def main() -> None:
    from allchats_sdk.max import MAXClient

    # Credentials shape depends on your host (device_id, auth_token, …).
    credentials = {
        "device_id": os.environ.get("MAX_DEVICE_ID", "device-1"),
    }

    client = MAXClient(
        account_id=os.environ.get("MAX_ACCOUNT_ID", "acc-1"),
        session_host=get_session_host(),
    )

    qr = await client.auth.start_qr(credentials)
    print("QR / auth payload from host:")
    print(qr)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
