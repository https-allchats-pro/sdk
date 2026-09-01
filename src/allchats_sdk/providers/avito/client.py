from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.avito.ru"
OAUTH_AUTHORIZE_URL = "https://www.avito.ru/oauth"
DEFAULT_SCOPES = "messenger:read,messenger:write,user:read"


class AvitoApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _encode_form(data: dict[str, str]) -> bytes:
    import urllib.parse

    return urllib.parse.urlencode(data).encode("utf-8")


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
            raise AvitoApiError(message, status=status, body=body) from exc
        except requests.RequestException as exc:
            raise AvitoApiError(str(exc)) from exc

    return await asyncio.to_thread(_do)


async def get_token_client_credentials(
    *,
    client_id: str,
    client_secret: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    return await _request(
        "POST",
        f"{API_BASE}/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=_encode_form(
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }
        ),
        proxies=proxies,
    )


async def get_token_authorization_code(
    *,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    return await _request(
        "POST",
        f"{API_BASE}/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=_encode_form(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            }
        ),
        proxies=proxies,
    )


async def refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    return await _request(
        "POST",
        f"{API_BASE}/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data=_encode_form(
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            }
        ),
        proxies=proxies,
    )


async def get_user_info(access_token: str, *, proxies: dict[str, str] | None = None) -> dict[str, Any]:
    return await _request(
        "GET",
        f"{API_BASE}/core/v1/accounts/self",
        headers={"Authorization": f"Bearer {access_token}"},
        proxies=proxies,
    )


def build_oauth_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: str = DEFAULT_SCOPES,
) -> str:
    import urllib.parse

    params = {
        "response_type": "code",
        "pro_users_flow": "true",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def token_expires_at_ms(token_response: dict[str, Any]) -> int:
    expires_in = int(token_response.get("expires_in") or 86400)
    return int(time.time() * 1000) + expires_in * 1000


async def send_chat_message(
    *,
    user_id: str,
    chat_id: str,
    access_token: str,
    text: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    import urllib.parse

    encoded_chat_id = urllib.parse.quote(chat_id, safe="")
    body = json.dumps(
        {"type": "text", "message": {"text": text}},
        ensure_ascii=False,
    ).encode("utf-8")
    return await _request(
        "POST",
        f"{API_BASE}/messenger/v1/accounts/{user_id}/chats/{encoded_chat_id}/messages",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=body,
        proxies=proxies,
    )


async def upload_avito_image(
    *,
    user_id: str,
    access_token: str,
    data: bytes,
    filename: str,
    content_type: str | None = None,
    proxies: dict[str, str] | None = None,
) -> str:
    if not data:
        raise AvitoApiError("empty image upload")

    def _do() -> str:
        safe_name = str(filename or "photo.jpg").strip() or "photo.jpg"
        mime = str(content_type or "image/jpeg").strip() or "image/jpeg"
        try:
            response = requests.post(
                f"{API_BASE}/messenger/v1/accounts/{user_id}/uploadImages",
                headers=_auth_headers(access_token),
                files={"uploadfile[]": (safe_name, data, mime)},
                timeout=60.0,
                proxies=proxies,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.HTTPError as exc:
            body: Any = None
            if exc.response is not None:
                try:
                    body = exc.response.json()
                except Exception:
                    body = exc.response.text
            message = str(body) if body else str(exc)
            status = exc.response.status_code if exc.response is not None else None
            raise AvitoApiError(message, status=status, body=body) from exc
        except requests.RequestException as exc:
            raise AvitoApiError(str(exc)) from exc

        if not isinstance(payload, dict) or not payload:
            raise AvitoApiError("empty image upload response")
        image_id = next(iter(payload.keys()))
        normalized = str(image_id or "").strip()
        if not normalized:
            raise AvitoApiError("image upload response has no image_id")
        return normalized

    return await asyncio.to_thread(_do)


async def send_chat_image_message(
    *,
    user_id: str,
    chat_id: str,
    access_token: str,
    image_id: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    import urllib.parse

    encoded_chat_id = urllib.parse.quote(chat_id, safe="")
    body = json.dumps({"image_id": str(image_id).strip()}, ensure_ascii=False).encode("utf-8")
    return await _request(
        "POST",
        f"{API_BASE}/messenger/v1/accounts/{user_id}/chats/{encoded_chat_id}/messages/image",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        data=body,
        proxies=proxies,
    )


async def delete_chat_message(
    *,
    user_id: str,
    chat_id: str,
    message_id: str,
    access_token: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    import urllib.parse

    encoded_chat_id = urllib.parse.quote(chat_id, safe="")
    encoded_message_id = urllib.parse.quote(str(message_id).strip(), safe="")
    return await _request(
        "DELETE",
        f"{API_BASE}/messenger/v1/accounts/{user_id}/chats/{encoded_chat_id}/messages/{encoded_message_id}",
        headers=_auth_headers(access_token),
        proxies=proxies,
    )


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


async def list_chats(
    *,
    user_id: str,
    access_token: str,
    limit: int = 50,
    offset: int = 0,
    unread_only: bool | None = None,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    import urllib.parse

    params: dict[str, str] = {
        "limit": str(max(1, min(limit, 100))),
        "offset": str(max(0, offset)),
    }
    if unread_only is not None:
        params["unread_only"] = "true" if unread_only else "false"
    query = urllib.parse.urlencode(params)
    return await _request(
        "GET",
        f"{API_BASE}/messenger/v2/accounts/{user_id}/chats?{query}",
        headers=_auth_headers(access_token),
        proxies=proxies,
    )


async def get_chat_messages(
    *,
    user_id: str,
    chat_id: str,
    access_token: str,
    limit: int = 50,
    offset: int = 0,
    proxies: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    import urllib.parse

    encoded_chat_id = urllib.parse.quote(chat_id, safe="")
    params = urllib.parse.urlencode(
        {
            "limit": str(max(1, min(limit, 100))),
            "offset": str(max(0, offset)),
        }
    )
    result = await _request(
        "GET",
        f"{API_BASE}/messenger/v3/accounts/{user_id}/chats/{encoded_chat_id}/messages/?{params}",
        headers=_auth_headers(access_token),
        proxies=proxies,
    )
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            return messages
    return []


async def subscribe_webhook(
    *,
    url: str,
    access_token: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = json.dumps({"url": url}, ensure_ascii=False).encode("utf-8")
    return await _request(
        "POST",
        f"{API_BASE}/messenger/v3/webhook",
        headers={**_auth_headers(access_token), "Content-Type": "application/json"},
        data=body,
        proxies=proxies,
    )


async def get_subscriptions(
    access_token: str,
    *,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    return await _request(
        "POST",
        f"{API_BASE}/messenger/v1/subscriptions",
        headers=_auth_headers(access_token),
        proxies=proxies,
    )


def extract_message_text(message: dict[str, Any]) -> str:
    msg_type = str(message.get("type") or "text").strip().lower()
    content = message.get("content") or {}
    if not isinstance(content, dict):
        return ""

    text = str(content.get("text") or "").strip()
    if text:
        return text

    if msg_type == "link":
        link = content.get("link") or {}
        if isinstance(link, dict):
            return str(link.get("text") or link.get("url") or "").strip()

    if msg_type == "image":
        return "[photo]"

    if msg_type == "item":
        item = content.get("item") or {}
        if isinstance(item, dict):
            title = str(item.get("title") or "").strip()
            if title:
                return title
        return "[item]"

    if msg_type == "location":
        location = content.get("location") or {}
        if isinstance(location, dict):
            return str(location.get("title") or location.get("text") or "").strip() or "[location]"

    if msg_type == "voice":
        return "[voice]"

    if msg_type == "call":
        return "[call]"

    if msg_type in {"deleted", "system"}:
        return ""

    return f"[{msg_type}]" if msg_type else ""


def chat_title_from_api(chat: dict[str, Any], *, owner_user_id: str) -> str:
    owner = str(owner_user_id or "").strip()
    for user in chat.get("users") or []:
        if not isinstance(user, dict):
            continue
        user_id = str(user.get("id") or "").strip()
        if user_id and user_id != owner:
            name = str(user.get("name") or "").strip()
            if name:
                return name

    context = chat.get("context") or {}
    if isinstance(context, dict):
        value = context.get("value") or {}
        if isinstance(value, dict):
            title = str(value.get("title") or "").strip()
            if title:
                return title

    return str(chat.get("id") or "").strip() or "Avito chat"


def chat_listing_from_api(chat: dict[str, Any]) -> dict[str, Any] | None:
    context = chat.get("context") or {}
    if not isinstance(context, dict):
        return None

    value = context.get("value") or {}
    if not isinstance(value, dict):
        return None

    item_id = value.get("id")
    title = str(value.get("title") or "").strip()
    price = str(value.get("price_string") or value.get("price") or "").strip()
    url = str(value.get("url") or "").strip()
    image_url = _pick_image_url(value.get("images") or value.get("image"))
    context_type = str(context.get("type") or "").strip().lower()
    city = _listing_city_from_value(value)

    if item_id is None and not title and not url and not image_url and not city:
        return None

    listing: dict[str, Any] = {}
    if item_id is not None:
        listing["id"] = str(item_id)
    if title:
        listing["title"] = title
    if price:
        listing["price"] = price
    if url:
        listing["url"] = url
    if image_url:
        listing["image_url"] = image_url
    if city:
        listing["city"] = city
    if context_type:
        listing["context_type"] = context_type
    return listing or None


async def get_item_info(
    *,
    user_id: str,
    item_id: str,
    access_token: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    import urllib.parse

    encoded_item_id = urllib.parse.quote(str(item_id).strip(), safe="")
    result = await _request(
        "GET",
        f"{API_BASE}/core/v1/accounts/{user_id}/items/{encoded_item_id}/",
        headers=_auth_headers(access_token),
        proxies=proxies,
    )
    if isinstance(result, dict):
        return result
    return {}


def item_city_from_api(item: dict[str, Any]) -> str:
    for key in ("location", "geo", "address_details"):
        city = _pick_named_location(item.get(key))
        if city:
            return city

    address = str(item.get("address") or "").strip()
    if address:
        if "," in address:
            return address.rsplit(",", 1)[-1].strip()
        return address
    return ""


async def enrich_listing_city(
    listing: dict[str, Any],
    *,
    user_id: str,
    access_token: str,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    if str(listing.get("city") or "").strip():
        return listing

    item_id = str(listing.get("id") or "").strip()
    if not item_id:
        return listing

    try:
        item = await get_item_info(
            user_id=user_id,
            item_id=item_id,
            access_token=access_token,
            proxies=proxies,
        )
        city = item_city_from_api(item)
        if city:
            enriched = dict(listing)
            enriched["city"] = city
            return enriched
    except AvitoApiError:
        logger.debug("failed to resolve avito listing city item=%s", item_id, exc_info=True)
    return listing


def _pick_named_location(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()

    if not isinstance(value, dict):
        return ""

    for key in ("city", "city_name", "name", "title", "region", "location_name"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        if isinstance(raw, dict):
            nested = _pick_named_location(raw)
            if nested:
                return nested
    return ""


def _listing_city_from_value(value: dict[str, Any]) -> str:
    for key in ("city", "city_name", "location_name", "region"):
        city = _pick_named_location(value.get(key))
        if city:
            return city

    for key in ("location", "geo", "address_details"):
        city = _pick_named_location(value.get(key))
        if city:
            return city

    address = str(value.get("address") or "").strip()
    if address:
        if "," in address:
            return address.rsplit(",", 1)[-1].strip()
        return address
    return ""


def _pick_image_url(value: Any) -> str | None:
    if isinstance(value, str):
        url = value.strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url
        return None

    if isinstance(value, dict):
        for key in ("640x480", "256x256", "128x128", "140x105", "64x64", "default", "url"):
            picked = _pick_image_url(value.get(key))
            if picked:
                return picked
        for nested in value.values():
            picked = _pick_image_url(nested)
            if picked:
                return picked
        return None

    if isinstance(value, list):
        for item in value:
            picked = _pick_image_url(item)
            if picked:
                return picked
    return None


def chat_avatar_from_api(chat: dict[str, Any], *, owner_user_id: str) -> str | None:
    owner = str(owner_user_id or "").strip()
    for user in chat.get("users") or []:
        if not isinstance(user, dict):
            continue
        user_id = str(user.get("id") or "").strip()
        if user_id and user_id != owner:
            profile = user.get("public_user_profile") or user.get("profile") or {}
            if isinstance(profile, dict):
                picked = _pick_image_url(profile.get("avatar") or profile.get("image"))
                if picked:
                    return picked
            picked = _pick_image_url(user.get("avatar") or user.get("image"))
            if picked:
                return picked

    context = chat.get("context") or {}
    if isinstance(context, dict):
        value = context.get("value") or {}
        if isinstance(value, dict):
            picked = _pick_image_url(value.get("images") or value.get("image"))
            if picked:
                return picked
    return None


def user_avatar_from_info(user_info: dict[str, Any]) -> str | None:
    profile = user_info.get("profile")
    if isinstance(profile, dict):
        picked = _pick_image_url(profile.get("avatar") or profile.get("image"))
        if picked:
            return picked
    return _pick_image_url(user_info.get("avatar") or user_info.get("image"))


def message_sent_at(message: dict[str, Any]) -> int | None:
    created = message.get("created")
    if isinstance(created, (int, float)) and created > 0:
        return int(created)
    return None
