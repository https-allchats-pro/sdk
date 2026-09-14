"""MAX: connect an account through your host SessionManager.

MAX sessions are host-owned. In the AllChats backend you already have a
``SessionManager`` — pass it as ``session_host``:

    from allchats_sdk.max import MAXClient

    client = MAXClient(account_id="acc-1", session_host=session_manager)
    await client.connect()

This script is a template: set ``get_session_host()`` to return your manager.
"""

from __future__ import annotations

import asyncio
import os


def get_session_host():
    """Return your host SessionManager (or compatible session_host)."""
    # Example (AllChats backend):
    #   from internal.core.session.manager import SessionManager
    #   return container.session_manager
    raise SystemExit(
        "Wire get_session_host() to your SessionManager, then re-run.\n"
        "See docstring in examples/max/connect.py"
    )


async def main() -> None:
    from allchats_sdk.max import MAXClient

    client = MAXClient(
        account_id=os.environ.get("MAX_ACCOUNT_ID", "acc-1"),
        session_host=get_session_host(),
    )

    status = await client.connect()
    print(f"connected state={getattr(status, 'state', status)}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
