from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from allchats_sdk.providers.discord.api import DiscordApiError, exchange_remote_auth_ticket
from allchats_sdk.providers.discord.remote_auth import DiscordRemoteAuthError, run_remote_auth
from allchats_sdk.observability import record_auth

if TYPE_CHECKING:
    from allchats_sdk.providers.discord.manager import DiscordAccountClient, DiscordClientManager

logger = logging.getLogger(__name__)


async def run_discord_qr_auth_worker(
    account_id: str,
    *,
    manager: DiscordClientManager,
    client: DiscordAccountClient,
    proxies: dict[str, str] | None = None,
) -> None:
    try:
        async def on_qr(qr_link: str, _fingerprint: str) -> None:
            client.auth_url = qr_link
            client.qr_status = "pending"
            manager.set_client_state(account_id, state_instance="qrWaiting", running=True)

        async def on_opened() -> None:
            client.qr_status = "opened"
            manager.set_client_state(account_id, state_instance="qrWaiting", running=True)

        async def exchange_ticket(ticket: str) -> dict[str, Any]:
            return await exchange_remote_auth_ticket(
                api_base=manager.api_base,
                ticket=ticket,
                proxies=proxies,
                user_agent=manager.user_agent,
            )

        result = await run_remote_auth(
            ws_url=manager.remote_auth_url,
            exchange_ticket=exchange_ticket,
            on_qr=on_qr,
            on_opened=on_opened,
            should_stop=lambda: not client.running,
            proxy_url=manager.proxy_url_from_proxies(proxies),
            user_agent=manager.user_agent,
        )

        await manager.finalize_auth(
            account_id,
            token=result.token,
            auth_method="qr",
        )
        record_auth("discord", "ok")
    except DiscordRemoteAuthError as exc:
        logger.warning("discord qr auth failed account=%s: %s", account_id[:8], exc)
        manager.set_client_state(
            account_id,
            state_instance="notAuthorized",
            error=str(exc),
            running=False,
        )
        record_auth("discord", "failed")
    except DiscordApiError as exc:
        logger.warning("discord qr ticket exchange failed account=%s: %s", account_id[:8], exc)
        manager.set_client_state(
            account_id,
            state_instance="notAuthorized",
            error=str(exc),
            running=False,
        )
        record_auth("discord", "failed")
    except Exception as exc:
        logger.exception("discord qr auth crashed account=%s", account_id[:8])
        manager.set_client_state(
            account_id,
            state_instance="notAuthorized",
            error=str(exc) or "qr auth failed",
            running=False,
        )
        record_auth("discord", "failed")
    finally:
        manager.cleanup_qr_auth(account_id)
