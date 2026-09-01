"""
VK QR-авторизация через мобильный API (как в официальных клиентах VK).
"""

from __future__ import annotations

import asyncio
import base64
from enum import IntEnum
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from allchats_sdk.providers.vk.native_api import (
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    SCOPE,
    USER_AGENT,
    VkNativeApiError,
    vk_method,
)

POLL_INTERVAL_SEC = 2.0


class QrStatus(IntEnum):
    CREATED = 0
    OPENED = 1
    APPROVED = 2
    DECLINED = 3
    EXPIRED = 4


class VkQrAuthError(Exception):
    pass


def _call(method: str, *, proxies: dict[str, str] | None = None, **params: object) -> Any:
    try:
        return vk_method(method, proxies=proxies, **params)
    except VkNativeApiError as exc:
        raise VkQrAuthError(str(exc)) from exc


def get_anonym_token(*, proxies: dict[str, str] | None = None) -> str:
    response = _call(
        "auth.getAnonymToken",
        proxies=proxies,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
    )
    return response["token"]


def get_auth_code(
    anonym_token: str,
    device_name: str = "VK Messenger Shop",
    *,
    proxies: dict[str, str] | None = None,
) -> tuple[str, str]:
    response = _call(
        "auth.getAuthCode",
        proxies=proxies,
        client_id=CLIENT_ID,
        scope=SCOPE,
        anonymous_token=anonym_token,
        device_name=device_name,
    )
    return response["auth_url"], response["auth_hash"]


def check_auth_code(
    anonym_token: str,
    auth_hash: str,
    *,
    web_auth: bool = False,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    params: dict[str, object] = {
        "anonymous_token": anonym_token,
        "auth_hash": auth_hash,
    }
    if web_auth:
        params["web_auth"] = 1
    return _call("auth.checkAuthCode", proxies=proxies, **params)


def fetch_oauth_hash(session: requests.Session, *, proxies: dict[str, str] | None = None) -> str:
    response = session.get(
        "https://oauth.vk.ru/authorize",
        params={
            "client_id": CLIENT_ID,
            "display": "mobile",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "response_type": "token",
            "revoke": 1,
            "v": "5.199",
        },
        headers={"User-Agent": USER_AGENT},
        allow_redirects=False,
        timeout=30,
        proxies=proxies,
    )

    location = response.headers.get("Location") or response.url
    query = parse_qs(urlparse(location).query)
    oauth_hash = query.get("return_auth_hash", [None])[0]

    if not oauth_hash:
        raise VkQrAuthError("Не удалось получить OAuth hash")

    return oauth_hash


def exchange_super_app_token(
    super_app_token: str,
    *,
    proxies: dict[str, str] | None = None,
) -> str:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "X-Origin": "https://id.vk.ru",
        }
    )
    if proxies:
        session.proxies.update(proxies)

    oauth_hash = fetch_oauth_hash(session, proxies=proxies)

    session.get(
        "https://login.vk.ru/",
        params={
            "act": "connect_code_auth",
            "token": super_app_token,
            "app_id": CLIENT_ID,
            "oauth_scope": SCOPE,
            "oauth_force_hash": 1,
            "is_registration": 0,
            "oauth_response_type": "token",
            "is_oauth_migrated_flow": 1,
            "version": 1,
            "to": base64.b64encode(REDIRECT_URI.encode()).decode(),
        },
        timeout=30,
        proxies=proxies,
    )

    connect_response = session.get(
        "https://login.vk.ru/",
        params={
            "act": "connect_internal",
            "app_id": CLIENT_ID,
            "oauth_version": 1,
            "version": 1,
        },
        timeout=30,
        proxies=proxies,
    )
    connect_response.raise_for_status()
    connect_json = connect_response.json()

    session_token = connect_json.get("data", {}).get("access_token")
    auth_user_hash = connect_json.get("data", {}).get("auth_user_hash")

    if not session_token or not auth_user_hash:
        raise VkQrAuthError("Не удалось завершить OAuth-сессию через login.vk.ru")

    token_response = _call(
        "auth.getOauthToken",
        proxies=proxies,
        access_token=session_token,
        app_id=CLIENT_ID,
        client_id=CLIENT_ID,
        scope=SCOPE,
        hash=oauth_hash,
        auth_user_hash=auth_user_hash,
        is_seamless_auth=0,
    )

    access_token = token_response.get("access_token")
    if not access_token:
        raise VkQrAuthError("auth.getOauthToken не вернул access_token")

    return access_token


def resolve_access_token(
    approved: dict[str, Any],
    *,
    proxies: dict[str, str] | None = None,
) -> str:
    if approved.get("access_token"):
        return str(approved["access_token"])

    super_app_token = approved.get("super_app_token")
    if super_app_token:
        return exchange_super_app_token(str(super_app_token), proxies=proxies)

    raise VkQrAuthError("VK не вернул токен после подтверждения QR")


def fetch_user_id(access_token: str, *, proxies: dict[str, str] | None = None) -> int:
    users = _call("users.get", proxies=proxies, access_token=access_token)
    if not users:
        raise VkQrAuthError("users.get вернул пустой ответ")
    return users[0]["id"]


def init_qr_session(
    device_name: str = "VK Messenger Shop",
    *,
    proxies: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    anonym_token = get_anonym_token(proxies=proxies)
    auth_url, auth_hash = get_auth_code(anonym_token, device_name=device_name, proxies=proxies)
    return auth_url, auth_hash, anonym_token


def resolve_approved_token(
    approved: dict[str, Any],
    anonym_token: str,
    auth_hash: str,
    *,
    proxies: dict[str, str] | None = None,
) -> tuple[str, int | None]:
    if not approved.get("access_token") and not approved.get("super_app_token"):
        approved = check_auth_code(anonym_token, auth_hash, web_auth=True, proxies=proxies)

    access_token = resolve_access_token(approved, proxies=proxies)
    user_id = approved.get("user_id")
    if user_id is not None:
        return access_token, int(user_id)
    return access_token, fetch_user_id(access_token, proxies=proxies)


async def init_qr_session_async(
    device_name: str = "VK Messenger Shop",
    *,
    proxies: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    return await asyncio.to_thread(init_qr_session, device_name, proxies=proxies)


async def check_auth_code_async(
    anonym_token: str,
    auth_hash: str,
    *,
    web_auth: bool = False,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        check_auth_code,
        anonym_token,
        auth_hash,
        web_auth=web_auth,
        proxies=proxies,
    )


async def resolve_approved_token_async(
    approved: dict[str, Any],
    anonym_token: str,
    auth_hash: str,
    *,
    proxies: dict[str, str] | None = None,
) -> tuple[str, int | None]:
    return await asyncio.to_thread(
        resolve_approved_token,
        approved,
        anonym_token,
        auth_hash,
        proxies=proxies,
    )
