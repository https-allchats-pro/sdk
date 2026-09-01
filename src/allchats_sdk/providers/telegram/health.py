"""Telegram connectivity checks."""

from __future__ import annotations

import asyncio
from typing import Any


async def ping_telegram_connect(
    *,
    app_id: int,
    app_hash: str,
    proxy: tuple | dict | None,
    connect_timeout: float = 20.0,
) -> str:
    """Connect to Telegram and return status: ``ok``, ``timeout``, or ``fail: ...``."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(
        StringSession(),
        app_id,
        app_hash,
        proxy=proxy,
        connection_retries=1,
        timeout=15,
    )
    try:
        await asyncio.wait_for(client.connect(), timeout=connect_timeout)
        return "ok"
    except asyncio.TimeoutError:
        return "timeout"
    except Exception as exc:
        return f"fail: {exc}"
    finally:
        await client.disconnect()


async def ping_telegram_from_settings(settings: Any) -> str:
    from allchats_sdk.providers.telegram.proxy import resolve_telegram_proxy

    if not settings.telegram.app_id or not str(settings.telegram.app_hash or "").strip():
        return "not_configured"

    telethon_proxy = resolve_telegram_proxy(settings=settings, credentials={})
    if telethon_proxy is None:
        return "no_proxy"

    return await ping_telegram_connect(
        app_id=settings.telegram.app_id,
        app_hash=str(settings.telegram.app_hash),
        proxy=telethon_proxy,
    )
