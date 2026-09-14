from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from allchats_sdk.providers.discord.api import (
    DiscordApiError,
    extract_captcha_challenge,
    is_captcha_challenge,
    login,
    submit_mfa_totp,
)
from allchats_sdk.internal.observability import record_auth

if TYPE_CHECKING:
    from allchats_sdk.providers.discord.manager import DiscordClientManager

logger = logging.getLogger(__name__)


async def run_discord_login_auth_worker(
    account_id: str,
    *,
    login_value: str,
    password: str,
    manager: DiscordClientManager,
    proxies: dict[str, str] | None = None,
) -> None:
    try:
        manager.set_client_state(account_id, state_instance="starting", running=True)
        payload = await login(
            api_base=manager.api_base,
            login=login_value,
            password=password,
            proxies=proxies,
            user_agent=manager.user_agent,
        )

        # Discord may re-issue captcha several times if the solve is rejected.
        for _ in range(3):
            if not is_captcha_challenge(payload):
                break
            challenge = extract_captcha_challenge(payload)
            if not challenge.get("captcha_sitekey"):
                raise DiscordApiError("discord captcha required but sitekey is missing", payload=payload)
            solution = await manager.wait_captcha_solution(account_id, challenge)
            payload = await login(
                api_base=manager.api_base,
                login=login_value,
                password=password,
                proxies=proxies,
                user_agent=manager.user_agent,
                captcha_key=solution,
                captcha_session_id=challenge.get("captcha_session_id") or None,
                captcha_rqtoken=challenge.get("captcha_rqtoken") or None,
            )
        else:
            if is_captcha_challenge(payload):
                raise DiscordApiError("discord captcha was not accepted", payload=payload)

        token = str(payload.get("token") or "").strip()
        if token:
            await manager.finalize_auth(account_id, token=token, auth_method="login")
            record_auth("discord", "ok")
            return

        if payload.get("mfa") or payload.get("totp") or payload.get("sms"):
            ticket = str(payload.get("ticket") or "").strip()
            if not ticket:
                raise DiscordApiError("mfa required but ticket is missing", payload=payload)

            manager._mfa_tickets[account_id] = ticket
            hint = "authenticator" if payload.get("totp") else ("sms" if payload.get("sms") else "mfa")
            code, _remember = await manager.wait_verification_code(
                account_id,
                kind="mfa",
                hint=hint,
            )
            mfa_payload = await submit_mfa_totp(
                api_base=manager.api_base,
                ticket=ticket,
                code=code,
                proxies=proxies,
                user_agent=manager.user_agent,
            )
            mfa_token = str(mfa_payload.get("token") or "").strip()
            if not mfa_token:
                raise DiscordApiError("mfa succeeded without token", payload=mfa_payload)
            await manager.finalize_auth(account_id, token=mfa_token, auth_method="login")
            record_auth("discord", "ok")
            return

        raise DiscordApiError("unexpected login response", payload=payload)
    except DiscordApiError as exc:
        logger.warning("discord login failed account=%s: %s", account_id[:8], exc)
        manager.set_client_state(
            account_id,
            state_instance="notAuthorized",
            error=str(exc),
            running=False,
        )
        record_auth("discord", "failed")
    except Exception as exc:
        logger.exception("discord login crashed account=%s", account_id[:8])
        manager.set_client_state(
            account_id,
            state_instance="notAuthorized",
            error=str(exc) or "login failed",
            running=False,
        )
        record_auth("discord", "failed")
    finally:
        manager.cleanup_login_auth(account_id)
