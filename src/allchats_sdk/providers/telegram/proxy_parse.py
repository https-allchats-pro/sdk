from __future__ import annotations

from typing import Any

from allchats_sdk.errors import ValidationError


def strip_env_quotes(value: str) -> str:
    raw = value.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1].strip()
    return raw


def parse_proxy_string(value: str, *, proxy_type: str = "socks5") -> dict[str, Any] | None:
    """Parse ``host:port`` or ``host:port:username:password``."""
    raw = strip_env_quotes(value)
    if not raw:
        return None

    parts = raw.split(":", 3)
    if len(parts) < 2:
        raise ValidationError("proxy must be in host:port[:username:password] format")

    host = parts[0].strip()
    try:
        port = int(parts[1].strip())
    except ValueError as exc:
        raise ValidationError("proxy port must be an integer") from exc

    if not host or port <= 0:
        raise ValidationError("proxy host and port are required")

    payload: dict[str, Any] = {
        "type": proxy_type,
        "host": host,
        "port": port,
        "rdns": True,
    }
    if len(parts) >= 3 and parts[2].strip():
        payload["username"] = parts[2].strip()
    if len(parts) == 4 and parts[3]:
        payload["password"] = parts[3]
    return payload


def normalize_proxy_config(raw: dict[str, Any] | str | None) -> dict[str, Any] | None:
    if not raw:
        return None

    if isinstance(raw, str):
        return parse_proxy_string(raw)

    host = str(raw.get("host") or raw.get("proxy_host") or "").strip()
    port_raw = raw.get("port", raw.get("proxy_port"))
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        port = 0

    if not host or port <= 0:
        return None

    proxy_type = str(raw.get("type") or raw.get("proxy_type") or "socks5").strip().lower()
    if proxy_type not in {"socks5", "socks4", "http"}:
        raise ValidationError(f"unsupported proxy type: {proxy_type}")

    payload: dict[str, Any] = {
        "type": proxy_type,
        "host": host,
        "port": port,
        "rdns": bool(raw.get("rdns", True)),
    }

    username = str(raw.get("username") or raw.get("proxy_username") or "").strip()
    password = str(raw.get("password") or raw.get("proxy_password") or "")
    if username:
        payload["username"] = username
    if password:
        payload["password"] = password
    return payload


def to_telethon_proxy(config: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_proxy_config(config)
    if normalized is None:
        raise ValidationError("proxy host and port are required")

    payload: dict[str, Any] = {
        "proxy_type": normalized["type"],
        "addr": normalized["host"],
        "port": normalized["port"],
        "rdns": normalized["rdns"],
    }
    if "username" in normalized:
        payload["username"] = normalized["username"]
    if "password" in normalized:
        payload["password"] = normalized["password"]
    return payload
