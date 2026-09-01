from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any

from allchats_sdk.providers.telegram.proxy import resolve_telegram_proxy
from allchats_sdk.errors import ValidationError
from allchats_sdk.observability import record_auth

if TYPE_CHECKING:
    from allchats_sdk.providers.telegram.manager import TelegramAccountClient, TelegramClientManager
    from allchats_sdk.config import Settings

logger = logging.getLogger(__name__)

QR_POLLING_INTERVAL_MS = 3000
QR_TTL_MS = 30_000
TELEGRAM_CONNECT_TIMEOUT_SEC = 15.0
TELEGRAM_CONNECT_TIMEOUT_WITH_PROXY_SEC = 45.0
TELEGRAM_QR_SETUP_BUFFER_SEC = 20.0


def telegram_connect_timeout(proxy: dict[str, Any] | None) -> float:
    return TELEGRAM_CONNECT_TIMEOUT_WITH_PROXY_SEC if proxy else TELEGRAM_CONNECT_TIMEOUT_SEC


def telegram_qr_wait_timeout(proxy: dict[str, Any] | None) -> float:
    connect_timeout = (
        TELEGRAM_CONNECT_TIMEOUT_WITH_PROXY_SEC if proxy else TELEGRAM_CONNECT_TIMEOUT_SEC
    )
    return connect_timeout + TELEGRAM_QR_SETUP_BUFFER_SEC


def _proxy_label(proxy: dict[str, Any] | None) -> str:
    if not proxy:
        return "direct"
    return f"{proxy.get('proxy_type', 'socks5')}://{proxy.get('addr')}:{proxy.get('port')}"


async def _fetch_password_hint(client: Any) -> str:
    try:
        from telethon.tl.functions.account import GetPasswordRequest

        password = await client(GetPasswordRequest())
        hint = str(getattr(password, "hint", "") or "").strip()
        return hint
    except Exception:
        logger.debug("telegram password hint unavailable", exc_info=True)
        return ""


async def run_telegram_qr_worker(
    *,
    settings: Settings,
    account_id: str,
    credentials: dict[str, Any],
    client_state: TelegramAccountClient,
    manager: TelegramClientManager,
) -> None:
    from telethon import TelegramClient
    from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError
    from telethon.sessions import StringSession

    session_data = str(credentials.get("session_data") or "").strip()
    user_id = str(credentials.get("user_id") or "").strip()
    if session_data and user_id:
        session = StringSession(session_data)
    else:
        session = StringSession()
    proxy = resolve_telegram_proxy(settings=settings, credentials=credentials)
    connect_timeout = (
        TELEGRAM_CONNECT_TIMEOUT_WITH_PROXY_SEC if proxy else TELEGRAM_CONNECT_TIMEOUT_SEC
    )
    logger.info(
        "telegram qr connect account=%s via %s timeout=%ss",
        account_id[:8],
        _proxy_label(proxy),
        int(connect_timeout),
    )
    client = TelegramClient(
        session,
        settings.telegram.app_id,
        settings.telegram.app_hash,
        proxy=proxy,
        connection_retries=3,
        retry_delay=2,
        timeout=20,
    )

    try:
        await asyncio.wait_for(client.connect(), timeout=connect_timeout)
        if await client.is_user_authorized():
            me = await client.get_me()
            await _persist_authorized(
                account_id=account_id,
                credentials=credentials,
                client=client,
                me=me,
                manager=manager,
            )
            return

        while client_state.running:
            qr_login = await client.qr_login()
            token = getattr(qr_login, "token", None)
            if isinstance(token, bytes):
                track_id = token.hex()
            elif token is not None:
                track_id = str(token)
            else:
                track_id = secrets.token_hex(16)
            expires_at = int(time.time() * 1000) + QR_TTL_MS
            manager.update_qr_state(
                account_id,
                qr_link=qr_login.url,
                track_id=track_id,
                polling_interval=QR_POLLING_INTERVAL_MS,
                expires_at=expires_at,
                state_instance="starting",
            )

            try:
                await asyncio.wait_for(qr_login.wait(), timeout=QR_TTL_MS / 1000 + 5)
                break
            except SessionPasswordNeededError:
                password_hint = await _fetch_password_hint(client)
                manager.set_client_state(
                    account_id,
                    state_instance="passwordRequired",
                    running=True,
                    password_hint=password_hint,
                )
                logger.info(
                    "telegram qr password required account=%s hint=%s",
                    account_id[:8],
                    bool(password_hint),
                )
                while client_state.running:
                    password = await manager.wait_password(account_id)
                    manager.set_client_state(
                        account_id,
                        state_instance="passwordRequired",
                        running=True,
                        password_hint=password_hint,
                        error="",
                    )
                    try:
                        await client.sign_in(password=password)
                        break
                    except PasswordHashInvalidError:
                        manager.set_client_state(
                            account_id,
                            state_instance="passwordRequired",
                            running=True,
                            password_hint=password_hint,
                            error="invalid password",
                        )
                        logger.warning(
                            "telegram qr invalid password account=%s",
                            account_id[:8],
                        )
                        record_auth("telegram", "failed")
                        continue
                break
            except asyncio.TimeoutError:
                continue

        me = await client.get_me()
        await _persist_authorized(
            account_id=account_id,
            credentials=credentials,
            client=client,
            me=me,
            manager=manager,
        )
    except asyncio.CancelledError:
        raise
    except ValidationError:
        raise
    except asyncio.TimeoutError:
        via = _proxy_label(proxy)
        message = (
            f"telegram connect timeout via {via}: "
            "check TELEGRAM_PROXY, proxy IP whitelist, and outbound access from VPS"
        )
        logger.error("telegram qr worker timeout account=%s", account_id[:8])
        manager.set_client_state(
            account_id,
            state_instance="error",
            error=message,
            running=False,
        )
        record_auth("telegram", "failed")
        return
    except Exception as exc:
        logger.exception("telegram qr worker failed account=%s", account_id[:8])
        manager.set_client_state(
            account_id,
            state_instance="error",
            error=str(exc),
            running=False,
        )
        record_auth("telegram", "failed")
    finally:
        await client.disconnect()


async def _persist_authorized(
    *,
    account_id: str,
    credentials: dict[str, Any],
    client: Any,
    me: Any,
    manager: TelegramClientManager,
    count_auth: bool = True,
) -> None:
    from telethon.sessions import StringSession

    from allchats_sdk.credentials import merge_credentials
    from allchats_sdk.events import CredentialsUpdatedEvent

    session_data = StringSession.save(client.session)
    incoming = {
        "device_id": str(credentials.get("device_id") or account_id),
        "user_id": str(me.id),
        "session_data": session_data,
    }
    if isinstance(credentials.get("proxy"), dict):
        incoming["proxy"] = credentials["proxy"]
    merged = merge_credentials(credentials, incoming)
    manager._creds.set(account_id, merged)
    nickname = None
    first = str(getattr(me, "first_name", "") or "").strip()
    last = str(getattr(me, "last_name", "") or "").strip()
    nickname = " ".join(part for part in (first, last) if part).strip() or None
    await manager.event_sink.on_credentials_updated(
        CredentialsUpdatedEvent(
            connection_id=account_id,
            provider="telegram",
            credentials=merged,
            user_id=str(me.id),
            nickname=nickname,
        )
    )
    manager.set_client_state(
        account_id,
        state_instance="authorized",
        user_id=str(me.id),
        running=True,
    )
    if count_auth:
        record_auth("telegram", "success")
