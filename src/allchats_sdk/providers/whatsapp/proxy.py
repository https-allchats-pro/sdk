from __future__ import annotations

import os
from typing import Any

from allchats_sdk.config import Settings, TelegramProxySettings
from allchats_sdk.providers.common.proxy import proxy_config_to_url
from allchats_sdk.providers.telegram.proxy_parse import (
    normalize_proxy_config,
    parse_proxy_string,
    strip_env_quotes,
)

__all__ = [
    "global_whatsapp_proxy_config",
    "proxy_config_to_url",
    "resolve_whatsapp_proxy",
    "whatsapp_proxy_label",
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


def global_whatsapp_proxy_config(settings: Settings) -> dict[str, Any] | None:
    from_config = proxy_settings_to_dict(settings.whatsapp.proxy)
    if from_config is not None:
        return from_config

    return parse_proxy_string(
        strip_env_quotes(os.environ.get("WHATSAPP_PROXY", "")),
        proxy_type=os.environ.get("WHATSAPP_PROXY_TYPE", "socks5") or "socks5",
    )


def resolve_whatsapp_proxy(
    settings: Settings,
    credentials: dict[str, Any] | None = None,
) -> Any:
    from neonize._binder import ProxySettings

    account_proxy = (credentials or {}).get("proxy")
    if isinstance(account_proxy, dict):
        config = normalize_proxy_config(account_proxy)
        if config is not None:
            return ProxySettings(proxy_address=proxy_config_to_url(config))

    global_proxy = global_whatsapp_proxy_config(settings)
    if global_proxy is not None:
        return ProxySettings(proxy_address=proxy_config_to_url(global_proxy))

    return None


def whatsapp_proxy_label(
    settings: Settings,
    credentials: dict[str, Any] | None = None,
) -> str | None:
    account_proxy = (credentials or {}).get("proxy")
    if isinstance(account_proxy, dict):
        config = normalize_proxy_config(account_proxy)
        if config is not None:
            return f"{config.get('type', 'socks5')}://{config['host']}:{config['port']}"

    global_proxy = global_whatsapp_proxy_config(settings)
    if global_proxy is not None:
        config = global_proxy
    else:
        return None

    return f"{config.get('type', 'socks5')}://{config['host']}:{config['port']}"
