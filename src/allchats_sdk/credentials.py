from __future__ import annotations

import uuid
from datetime import datetime
from random import randint
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator


class MaxNativeCredentials(BaseModel):
    model_config = ConfigDict(extra="allow")

    protocol: Literal["native"] = "native"
    device_id: str
    mt_instance_id: str
    client_session_id: int = 0
    auth_token: str = ""
    user_id: str = ""

    @field_validator("client_session_id", mode="before")
    @classmethod
    def _parse_client_session_id(cls, value: Any) -> int:
        return parse_client_session_id(value)


class TelegramProxyCredentials(BaseModel):
    type: Literal["socks5", "socks4", "http"] = "socks5"
    host: str
    port: int
    username: str = ""
    password: str = ""
    rdns: bool = True


class TelegramCredentials(BaseModel):
    model_config = ConfigDict(extra="allow")

    device_id: str
    user_id: str = ""
    session_data: str = ""
    proxy: TelegramProxyCredentials | None = None


SENSITIVE_CREDENTIAL_KEYS = frozenset(
    {
        "auth_token",
        "api_token_instance",
        "access_token",
        "session_data",
        "proxy_password",
        "client_secret",
        "refresh_token",
        "device_id",
        "token",
    }
)


def parse_client_session_id(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return int(str(value).strip())


def ensure_native_max_credentials(
    credentials: dict[str, Any] | None,
    *,
    account_id: str,
    proxy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(credentials or {})
    if proxy is not None:
        merged["proxy"] = proxy
    if not str(merged.get("mt_instance_id") or "").strip():
        merged["mt_instance_id"] = str(uuid.uuid4())
    if merged.get("client_session_id") in (None, "", 0):
        merged["client_session_id"] = randint(1, 70)
    merged["protocol"] = "native"
    merged["device_id"] = str(merged.get("device_id") or account_id).strip() or account_id
    merged.setdefault("auth_token", "")
    merged.setdefault("user_id", "")
    merged["client_session_id"] = parse_client_session_id(merged["client_session_id"])
    return merged


def new_telegram_credentials(
    *,
    account_id: str,
    proxy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    credentials: dict[str, Any] = {
        "device_id": account_id,
        "user_id": "",
        "session_data": "",
    }
    if proxy:
        credentials["proxy"] = proxy
    return credentials


def new_avito_credentials(*, account_id: str, proxy: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": account_id,
        "user_id": "",
        "auth_method": "",
        "client_id": "",
        "access_token": "",
        "refresh_token": "",
        "token_expires_at": 0,
    }
    if proxy is not None:
        payload["proxy"] = proxy
    return payload


def new_vk_credentials(*, account_id: str, proxy: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": account_id,
        "user_id": "",
        "auth_method": "",
        "access_token": "",
        "refresh_token": "",
        "token_expires_at": 0,
        "vk_device_id": "",
        "state_instance": "",
    }
    if proxy is not None:
        payload["proxy"] = proxy
    return payload


def vk_authorized(credentials: dict[str, Any]) -> bool:
    return bool(str(credentials.get("user_id") or "").strip()) and bool(
        str(credentials.get("access_token") or "").strip()
    )


def new_whatsapp_credentials(*, account_id: str, proxy: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "protocol": "web",
        "device_id": account_id,
        "user_id": "",
        "state_instance": "",
    }
    if proxy is not None:
        payload["proxy"] = proxy
    return payload


def whatsapp_authorized(credentials: dict[str, Any]) -> bool:
    return str(credentials.get("state_instance") or "").strip() == "authorized"


def new_discord_credentials(*, account_id: str, proxy: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "device_id": account_id,
        "user_id": "",
        "token": "",
        "auth_method": "",
        "state_instance": "",
    }
    if proxy is not None:
        payload["proxy"] = proxy
    return payload


def discord_authorized(credentials: dict[str, Any]) -> bool:
    return bool(str(credentials.get("user_id") or "").strip()) and bool(
        str(credentials.get("token") or "").strip()
    )


def avito_authorized(credentials: dict[str, Any]) -> bool:
    return bool(str(credentials.get("user_id") or "").strip()) and bool(
        str(credentials.get("access_token") or "").strip()
    )


def sanitize_credentials(creds: dict[str, Any] | None) -> dict[str, Any]:
    if not creds:
        return {}
    sanitized: dict[str, Any] = {}
    for key, value in creds.items():
        if key == "proxy" and isinstance(value, dict):
            proxy_copy = dict(value)
            if proxy_copy.get("password"):
                proxy_copy["password"] = "***"
            sanitized[key] = proxy_copy
            continue
        if key in SENSITIVE_CREDENTIAL_KEYS and value:
            sanitized[key] = "***"
        else:
            sanitized[key] = value
    return sanitized


def telegram_authorized(credentials: dict[str, Any]) -> bool:
    if str(credentials.get("user_id") or "").strip():
        return True
    return is_authorized(credentials, "telegram")


def is_authorized(creds: dict[str, Any], messenger_type: str) -> bool:
    if messenger_type == "native":
        return True
    if messenger_type == "telegram":
        return bool(str(creds.get("session_data") or "").strip())
    if messenger_type == "avito":
        return avito_authorized(creds)
    if messenger_type == "whatsapp":
        return whatsapp_authorized(creds)
    if messenger_type == "vk":
        return vk_authorized(creds)
    if messenger_type == "discord":
        return discord_authorized(creds)

    protocol = str(creds.get("protocol") or "native").strip().lower()
    if protocol in {"green", "cloud"}:
        return whatsapp_authorized(creds)

    return bool(str(creds.get("auth_token") or "").strip())


def merge_credentials(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(incoming)
    if "client_session_id" in merged:
        merged["client_session_id"] = parse_client_session_id(merged["client_session_id"])
    return merged


def account_avatar_url(credentials: dict[str, Any] | None) -> str | None:
    if not credentials:
        return None
    url = str(credentials.get("avatar_url") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return None


def avito_sync_started_at_ms(
    credentials: dict[str, Any],
    *,
    fallback: datetime | None = None,
) -> int | None:
    value = credentials.get("sync_started_at")
    if isinstance(value, (int, float)) and value > 0:
        return int(value)
    if fallback is not None:
        return int(fallback.timestamp() * 1000)
    return None


def account_to_response(account: Any) -> dict[str, Any]:
    credentials = account.credentials or {}
    return {
        "id": account.id,
        "messenger_type": account.messenger_type,
        "nickname": account.nickname,
        "avatar_url": account_avatar_url(credentials),
        "credentials": sanitize_credentials(credentials),
        "is_active": account.is_active,
        "is_authorized": is_authorized(credentials, account.messenger_type),
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }
