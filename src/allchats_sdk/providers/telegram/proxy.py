from __future__ import annotations

import os
from typing import Any

from allchats_sdk.providers.telegram.proxy_parse import (
    normalize_proxy_config,
    parse_proxy_string,
    strip_env_quotes,
    to_telethon_proxy,
)
from allchats_sdk.config import Settings, TelegramProxySettings

__all__ = [
    "global_proxy_config",
    "normalize_proxy_config",
    "parse_proxy_string",
    "proxy_settings_to_dict",
    "resolve_telegram_proxy",
    "strip_env_quotes",
    "to_telethon_proxy",
]


def proxy_settings_to_dict(proxy: TelegramProxySettings | None) -> dict[str, Any] | None:
    if proxy is None or not proxy.is_configured():
        return None
    payload: dict[str, Any] = {
        "type": proxy.type,
        "host": proxy.host.strip(),
        "port": proxy.port,
        "rdns": proxy.rdns,
    }
    if proxy.username.strip():
        payload["username"] = proxy.username.strip()
    if proxy.password:
        payload["password"] = proxy.password
    return payload


def global_proxy_config(settings: Settings) -> dict[str, Any] | None:
    global_proxy = proxy_settings_to_dict(settings.telegram.proxy)
    if global_proxy is not None:
        return global_proxy

    return parse_proxy_string(
        os.environ.get("TELEGRAM_PROXY", ""),
        proxy_type=os.environ.get("TELEGRAM_PROXY_TYPE", "socks5") or "socks5",
    )


def resolve_telegram_proxy(
    *,
    settings: Settings,
    credentials: dict[str, Any],
) -> dict[str, Any] | None:
    account_proxy = credentials.get("proxy")
    if isinstance(account_proxy, dict):
        normalized = normalize_proxy_config(account_proxy)
        if normalized is not None:
            return to_telethon_proxy(normalized)

    global_proxy = global_proxy_config(settings)
    if global_proxy is not None:
        return to_telethon_proxy(global_proxy)

    return None
