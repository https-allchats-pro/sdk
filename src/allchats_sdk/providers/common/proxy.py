from __future__ import annotations

from typing import Any
from urllib.parse import quote

from allchats_sdk.providers.telegram.proxy_parse import normalize_proxy_config

__all__ = [
    "proxy_config_to_url",
    "proxy_url_from_config",
    "proxy_url_from_credentials",
    "requests_proxies_from_config",
    "requests_proxies_from_credentials",
    "resolve_account_proxy_config",
]


def resolve_account_proxy_config(
    credentials: dict[str, Any] | None,
    *,
    global_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    account_proxy = (credentials or {}).get("proxy")
    if isinstance(account_proxy, dict):
        normalized = normalize_proxy_config(account_proxy)
        if normalized is not None:
            return normalized
    return global_config


def proxy_config_to_url(config: dict[str, Any]) -> str:
    normalized = normalize_proxy_config(config)
    if normalized is None:
        raise ValueError("proxy host and port are required")

    proxy_type = normalized["type"]
    host = normalized["host"]
    port = normalized["port"]
    username = normalized.get("username", "")
    password = normalized.get("password", "")

    if username:
        user = quote(str(username), safe="")
        pwd = quote(str(password or ""), safe="")
        return f"{proxy_type}://{user}:{pwd}@{host}:{port}"
    return f"{proxy_type}://{host}:{port}"


def proxy_url_from_config(config: dict[str, Any] | None) -> str | None:
    if config is None:
        return None
    return proxy_config_to_url(config)


def requests_proxies_from_config(config: dict[str, Any] | None) -> dict[str, str] | None:
    url = proxy_url_from_config(config)
    if not url:
        return None
    return {"http": url, "https": url}


def proxy_url_from_credentials(
    credentials: dict[str, Any] | None,
    *,
    global_config: dict[str, Any] | None = None,
) -> str | None:
    return proxy_url_from_config(
        resolve_account_proxy_config(credentials, global_config=global_config)
    )


def requests_proxies_from_credentials(
    credentials: dict[str, Any] | None,
    *,
    global_config: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    return requests_proxies_from_config(
        resolve_account_proxy_config(credentials, global_config=global_config)
    )
