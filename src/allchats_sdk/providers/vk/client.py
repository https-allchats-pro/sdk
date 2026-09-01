from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from allchats_sdk.providers.vk.native_api import (
    API_VERSION,
    VkNativeApiError,
    get_user_info as native_get_user_info,
    send_message_async as native_send_message_async,
    vk_method_async,
)
VK_ID_AUTHORIZE_URL = "https://id.vk.ru/authorize"
VK_ID_TOKEN_URL = "https://id.vk.ru/oauth2/auth"
VK_ID_USER_INFO_URL = "https://id.vk.ru/oauth2/user_info"
DEFAULT_SCOPES = ""


class VkApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def normalize_scopes(scopes: str) -> str:
    raw = scopes.strip() or DEFAULT_SCOPES
    return " ".join(part for part in raw.replace(",", " ").split() if part)


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def generate_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: float = 30.0,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        import requests

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                data=data,
                timeout=timeout,
                proxies=proxies,
            )
            response.raise_for_status()
            raw = response.text
            if not raw.strip():
                return {}
            return json.loads(raw)
        except requests.HTTPError as exc:
            body: Any = None
            if exc.response is not None:
                try:
                    body = exc.response.json()
                except Exception:
                    body = exc.response.text
            message = str(body) if body else str(exc)
            status = exc.response.status_code if exc.response is not None else None
            raise VkApiError(message, status=status, body=body) from exc
        except requests.RequestException as exc:
            raise VkApiError(str(exc)) from exc

    return await asyncio.to_thread(_do)


async def _post_form(
    url: str,
    fields: dict[str, str],
    *,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    return await _request(
        "POST",
        url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=body,
        proxies=proxies,
    )


async def vk_api_call(
    method: str,
    *,
    access_token: str,
    params: dict[str, Any] | None = None,
    proxies: dict[str, str] | None = None,
) -> Any:
    try:
        return await vk_method_async(
            method,
            access_token=access_token,
            proxies=proxies,
            **(params or {}),
        )
    except VkNativeApiError as exc:
        raise VkApiError(str(exc)) from exc


async def get_user_info(*, access_token: str, proxies: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(native_get_user_info, access_token=access_token, proxies=proxies)
    except VkNativeApiError as exc:
        raise VkApiError(str(exc)) from exc


async def get_vk_id_user_info(
    *,
    access_token: str,
    client_id: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = await _post_form(
        VK_ID_USER_INFO_URL,
        {
            "access_token": access_token,
            "client_id": client_id,
        },
        proxies=proxies,
    )
    user = payload.get("user")
    if isinstance(user, dict):
        return user
    raise VkApiError("failed to resolve vk id user")


async def send_message(
    *,
    access_token: str,
    peer_id: int,
    text: str,
    random_id: int | None = None,
    reply_to: int | None = None,
    forward_messages: str | None = None,
    proxies: dict[str, str] | None = None,
) -> int:
    try:
        return await native_send_message_async(
            access_token=access_token,
            peer_id=peer_id,
            text=text,
            random_id=random_id,
            reply_to=reply_to,
            forward_messages=forward_messages,
            proxies=proxies,
        )
    except VkNativeApiError as exc:
        raise VkApiError(str(exc)) from exc


async def exchange_vk_id_token(
    *,
    client_id: str,
    service_token: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    device_id: str,
    state: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not service_token.strip():
        raise VkApiError("service_token (VK_APP_SECRET) is required for VK ID token exchange")
    fields = {
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
        "code": code.strip(),
        "client_id": client_id,
        "device_id": device_id.strip(),
        "state": state,
        "service_token": service_token.strip(),
    }
    return await _post_form(VK_ID_TOKEN_URL, fields, proxies=proxies)


async def refresh_vk_id_token(
    *,
    client_id: str,
    service_token: str,
    refresh_token: str,
    device_id: str,
    state: str = "",
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not service_token.strip():
        raise VkApiError("service_token (VK_APP_SECRET) is required for VK ID token refresh")
    fields = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token.strip(),
        "client_id": client_id,
        "device_id": device_id.strip(),
        "service_token": service_token.strip(),
    }
    if state.strip():
        fields["state"] = state.strip()
    return await _post_form(VK_ID_TOKEN_URL, fields, proxies=proxies)


def build_vk_id_oauth_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    scopes: str = "",
) -> str:
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    normalized_scopes = normalize_scopes(scopes)
    if normalized_scopes:
        params["scope"] = normalized_scopes
    return f"{VK_ID_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def build_oauth_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: str,
    code_challenge: str,
) -> str:
    if not code_challenge:
        raise ValueError("code_challenge is required for VK ID OAuth")
    return build_vk_id_oauth_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        scopes=normalize_scopes(scopes),
    )


def token_expires_at_ms(token_response: dict[str, Any]) -> int:
    import time

    expires_in = int(token_response.get("expires_in") or 3600)
    return int(time.time() * 1000) + expires_in * 1000


def extract_user_nickname(user_info: dict[str, Any]) -> str | None:
    first = str(user_info.get("first_name") or "").strip()
    last = str(user_info.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first, last) if part).strip()
    return full_name or None


def peer_id_from_external_chat_id(chat_id: str) -> int:
    raw = chat_id.strip()
    if not raw:
        raise ValueError("chat_id is required")
    return int(raw)


def external_chat_id_from_peer(peer_id: int | str) -> str:
    return str(peer_id)
