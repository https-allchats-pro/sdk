from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import requests

from allchats_sdk.providers.avito.client import (
    AvitoApiError,
    send_chat_image_message,
    upload_avito_image,
)
from allchats_sdk.types.media import MESSAGE_TYPE_PHOTO, PHOTO_MESSAGE_TEXT, guess_media_extension
from allchats_sdk.types.voice import MESSAGE_TYPE_VOICE, VOICE_MESSAGE_TEXT

logger = logging.getLogger(__name__)

API_BASE = "https://api.avito.ru"
AVITO_VOICE_DEFAULT_EXTENSION = ".m4a"


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def extract_avito_image_url(message: dict[str, Any]) -> str | None:
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, dict):
        return None

    image = content.get("image")
    if isinstance(image, str) and image.startswith("http"):
        return image.strip()

    if isinstance(image, dict):
        sizes = image.get("sizes")
        if isinstance(sizes, dict) and sizes:
            def _area(key: str) -> int:
                parts = str(key).lower().replace(" ", "").split("x")
                if len(parts) != 2:
                    return 0
                try:
                    return int(parts[0]) * int(parts[1])
                except ValueError:
                    return 0

            best_key = max(sizes.keys(), key=lambda key: _area(str(key)))
            url = sizes.get(best_key)
            if isinstance(url, str) and url.startswith("http"):
                return url.strip()
        for key in ("url", "src", "href"):
            url = image.get(key)
            if isinstance(url, str) and url.startswith("http"):
                return url.strip()

    for key in ("image_url", "url"):
        url = content.get(key)
        if isinstance(url, str) and url.startswith("http"):
            return url.strip()
    return None


def extract_avito_voice_id(message: dict[str, Any]) -> str | None:
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, dict):
        return None
    voice = content.get("voice")
    if isinstance(voice, dict):
        voice_id = str(voice.get("voice_id") or voice.get("id") or "").strip()
        if voice_id:
            return voice_id
    voice_id = str(content.get("voice_id") or "").strip()
    return voice_id or None


def parse_avito_voice_urls(data: dict[str, Any]) -> dict[str, str]:
    """Map voice_id -> temporary download URL from getVoiceFiles response."""
    voices: Any = None
    if isinstance(data, dict):
        voices = data.get("voices_urls")
        if not isinstance(voices, dict):
            voices = data.get("voices")
    if isinstance(voices, dict):
        return {
            str(key): str(value).strip()
            for key, value in voices.items()
            if str(value).strip().startswith("http")
        }
    if isinstance(voices, list):
        result: dict[str, str] = {}
        for item in voices:
            if not isinstance(item, dict):
                continue
            voice_id = str(item.get("voice_id") or item.get("id") or "").strip()
            url = str(item.get("url") or item.get("link") or "").strip()
            if voice_id and url.startswith("http"):
                result[voice_id] = url
        return result
    return {}


async def get_avito_voice_files(
    *,
    user_id: str,
    access_token: str,
    voice_ids: list[str],
    proxies: dict[str, str] | None = None,
) -> dict[str, str]:
    from allchats_sdk.providers.avito.client import _request

    ids = [str(item).strip() for item in voice_ids if str(item).strip()]
    if not ids:
        return {}
    params = "&".join(f"voice_ids={item}" for item in ids)
    data = await _request(
        "GET",
        f"{API_BASE}/messenger/v1/accounts/{user_id}/getVoiceFiles?{params}",
        headers=_auth_headers(access_token),
        proxies=proxies,
    )
    return parse_avito_voice_urls(data if isinstance(data, dict) else {})


def download_avito_url(
    url: str,
    *,
    proxies: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> bytes:
    response = requests.get(url, timeout=timeout, proxies=proxies)
    response.raise_for_status()
    data = response.content
    if not data:
        raise AvitoApiError("empty media download")
    return data


def guess_extension_from_url(url: str, *, default: str = ".bin") -> str:
    path = urlparse(url).path
    guessed = guess_media_extension(None, path)
    return guessed if guessed else default


def avito_media_fields(message: dict[str, Any]) -> dict[str, Any] | None:
    msg_type = str(message.get("type") or "").strip().lower()
    if msg_type == "image" or extract_avito_image_url(message):
        return {
            "message_type": MESSAGE_TYPE_PHOTO,
            "text": PHOTO_MESSAGE_TEXT,
            "kind": "image",
        }
    if msg_type == "voice" or extract_avito_voice_id(message):
        return {
            "message_type": MESSAGE_TYPE_VOICE,
            "text": VOICE_MESSAGE_TEXT,
            "kind": "voice",
        }
    return None


async def send_avito_image_message(
    *,
    user_id: str,
    chat_id: str,
    access_token: str,
    data: bytes,
    filename: str,
    content_type: str | None = None,
    proxies: dict[str, str] | None = None,
) -> dict[str, Any]:
    image_id = await upload_avito_image(
        user_id=user_id,
        access_token=access_token,
        data=data,
        filename=filename,
        content_type=content_type,
        proxies=proxies,
    )
    return await send_chat_image_message(
        user_id=user_id,
        chat_id=chat_id,
        access_token=access_token,
        image_id=image_id,
        proxies=proxies,
    )
