from __future__ import annotations

import base64
import binascii
import asyncio
import logging
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import requests
from pydantic import ValidationError

from allchats_sdk.providers.max.trace import max_trace
from allchats_sdk.types.media import (
    IMAGE_EXTENSIONS,
    MESSAGE_TYPE_DOCUMENT,
    MESSAGE_TYPE_GIF,
    MESSAGE_TYPE_PHOTO,
    MESSAGE_TYPE_STICKER,
    MESSAGE_TYPE_VIDEO,
    guess_media_extension,
    media_placeholder_text,
)

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://web.max.ru/",
}


@dataclass(slots=True)
class MaxMediaItem:
    attachment: Any
    message_type: str
    filename: str | None = None


def _message_attaches(message: Any) -> list[Any]:
    attaches = getattr(message, "attaches", None) or getattr(message, "attachments", None)
    if not isinstance(attaches, list):
        return []
    return attaches


def find_audio_attachment(message: Any) -> Any | None:
    for attach in _message_attaches(message):
        attach_type = _attachment_type_name(attach)
        if attach_type in {"AUDIO", "UNSUPPORTED"}:
            if attach_type == "UNSUPPORTED" and getattr(attach, "audio_id", None) is None:
                if getattr(attach, "token", None) is None and getattr(attach, "url", None) is None:
                    continue
            return attach
    return None


def audio_duration_ms(attach: Any) -> int | None:
    duration = getattr(attach, "duration", None)
    if not isinstance(duration, int) or duration <= 0:
        return None
    attach_type = _attachment_type_name(attach)
    if attach_type == "UNSUPPORTED":
        return duration
    return duration * 1000


def _attachment_type_name(attach: Any) -> str:
    type_value = getattr(attach, "type", None)
    if type_value is None:
        type_value = getattr(attach, "_type", None)
    if isinstance(type_value, Enum):
        return str(type_value.value).strip().upper()
    if type_value is not None:
        raw = str(type_value).strip().upper()
        if raw:
            return raw
    class_name = attach.__class__.__name__
    if class_name.endswith("Attachment"):
        return class_name[: -len("Attachment")].upper()
    return class_name.upper()


def _needs_full_max_message(message: Any) -> bool:
    attaches = _message_attaches(message)
    if not attaches:
        return True

    audio = find_audio_attachment(message)
    if audio is not None and not str(getattr(audio, "url", "") or "").strip():
        return True

    media_items = extract_max_media_items(message)
    if not media_items:
        return True

    for item in media_items:
        attach = item.attachment
        if item.message_type == MESSAGE_TYPE_PHOTO:
            if not _photo_has_download_source(attach):
                return True
        elif item.message_type == MESSAGE_TYPE_STICKER:
            if not str(getattr(attach, "url", "") or "").strip():
                return True
        elif item.message_type in {MESSAGE_TYPE_VIDEO, MESSAGE_TYPE_GIF}:
            if not int(getattr(attach, "video_id", 0) or 0):
                return True
        elif item.message_type == MESSAGE_TYPE_DOCUMENT:
            if not int(getattr(attach, "file_id", 0) or 0):
                return True
            if not str(getattr(attach, "name", "") or "").strip():
                return True

    return False


def _max_message_chat_ids(
    client: Any,
    chat_id: int,
    *,
    sender: int | None = None,
    me_id: int | None = None,
) -> list[int]:
    chat_ids: list[int] = []

    def add(value: Any) -> None:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return
        if normalized not in chat_ids:
            chat_ids.append(normalized)

    add(chat_id)
    if sender is not None:
        add(sender)
    if sender is not None and me_id is not None:
        try:
            add(int(sender) ^ int(me_id))
        except (TypeError, ValueError):
            pass

    for chat in getattr(client, "chats", None) or []:
        participants = getattr(chat, "participants", None) or {}
        if sender is not None:
            try:
                sender_id = int(sender)
            except (TypeError, ValueError):
                continue
            if sender_id in participants:
                add(getattr(chat, "id", None))

    return chat_ids


def _decode_preview_data(value: Any) -> bytes | None:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.startswith("http://") or raw.startswith("https://"):
            return None
        try:
            return base64.b64decode(raw, validate=False)
        except (ValueError, binascii.Error):
            return None
    return None


_MEDIA_ATTACH_TYPES = frozenset({"PHOTO", "VIDEO", "FILE", "STICKER", "AUDIO"})


def _raw_payload_attaches(payload: dict[str, Any]) -> list[dict[str, Any]]:
    message_data = payload.get("message")
    if not isinstance(message_data, dict):
        message_data = payload
    attaches = message_data.get("attaches") or message_data.get("attachments") or []
    if not isinstance(attaches, list):
        return []
    return [item for item in attaches if isinstance(item, dict)]


def _raw_attach_type(attach: dict[str, Any]) -> str:
    return str(attach.get("_type") or attach.get("type") or "").strip().upper()


def _raw_attach_has_media_keys(attach: dict[str, Any]) -> bool:
    if _raw_attach_type(attach) in _MEDIA_ATTACH_TYPES:
        return True
    media_keys = (
        "photoId",
        "photo_id",
        "fileId",
        "file_id",
        "videoId",
        "video_id",
        "baseUrl",
        "base_url",
        "previewData",
        "preview_data",
    )
    return any(key in attach for key in media_keys)


def _attach_from_raw_dict(data: dict[str, Any]) -> SimpleNamespace:
    attach_type = _raw_attach_type(data)
    return SimpleNamespace(
        type=attach_type,
        _type=attach_type,
        base_url=str(data.get("baseUrl") or data.get("base_url") or "").strip(),
        base_raw_url=str(data.get("baseRawUrl") or data.get("base_raw_url") or "").strip(),
        url=str(data.get("url") or "").strip(),
        photo_id=int(data.get("photoId") or data.get("photo_id") or 0),
        photo_token=str(data.get("photoToken") or data.get("photo_token") or "").strip(),
        preview_data=_decode_preview_data(data.get("previewData") or data.get("preview_data")),
        file_id=int(data.get("fileId") or data.get("file_id") or 0),
        name=str(data.get("name") or "").strip(),
        token=str(data.get("token") or "").strip(),
        video_id=int(data.get("videoId") or data.get("video_id") or 0),
        video_type=int(data.get("videoType") or data.get("video_type") or 0),
    )


def parse_lenient_max_message(payload: dict[str, Any] | None) -> SimpleNamespace | None:
    if not isinstance(payload, dict):
        return None

    message_data = payload.get("message")
    if not isinstance(message_data, dict):
        message_data = payload

    message_id = message_data.get("id")
    if message_id is None:
        return None

    chat_id = payload.get("chatId", payload.get("chat_id"))
    if chat_id is None:
        chat_id = message_data.get("chatId", message_data.get("chat_id"))

    attaches_raw = message_data.get("attaches") or message_data.get("attachments") or []
    attaches: list[SimpleNamespace] = []
    if isinstance(attaches_raw, list):
        for item in attaches_raw:
            if isinstance(item, dict):
                attaches.append(_attach_from_raw_dict(item))

    return SimpleNamespace(
        id=message_id,
        chat_id=chat_id,
        sender=message_data.get("sender"),
        text=str(message_data.get("text") or ""),
        time=int(message_data.get("time") or 0),
        attaches=attaches,
    )


def _message_payload_dict(payload: dict[str, Any]) -> dict[str, Any]:
    message_data = payload.get("message")
    if not isinstance(message_data, dict):
        return payload

    merged = dict(message_data)
    for key in ("chatId", "chat_id", "prevMessageId", "ttl", "unread", "mark"):
        value = payload.get(key)
        if value is not None:
            merged[key if key != "chat_id" else "chatId"] = value
    return merged


def strict_max_message_valid(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    try:
        from pymax.types.domain import Message

        Message.model_validate(_message_payload_dict(payload))
    except ValidationError:
        return False
    return True


def payload_has_media_hint(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False

    for attach in _raw_payload_attaches(payload):
        if _raw_attach_has_media_keys(attach):
            return True

    message = parse_lenient_max_message(payload)
    if message is None:
        return False
    if extract_max_media_items(message):
        return True
    if find_audio_attachment(message) is not None:
        return True
    return not str(getattr(message, "text", "") or "").strip()


def merge_strict_max_message(payload: dict[str, Any]) -> Any | None:
    lenient = parse_lenient_max_message(payload)
    if lenient is None:
        return None
    if not strict_max_message_valid(payload):
        return lenient

    try:
        from pymax.types.domain import Message

        strict = Message.model_validate(_message_payload_dict(payload))
    except ValidationError:
        return lenient

    if strict.chat_id is None and lenient.chat_id is not None:
        strict.chat_id = lenient.chat_id

    strict_has_media = bool(
        extract_max_media_items(strict) or find_audio_attachment(strict) is not None
    )
    lenient_has_media = bool(
        extract_max_media_items(lenient) or find_audio_attachment(lenient) is not None
    )
    if strict_has_media and lenient_has_media:
        if _needs_full_max_message(strict) and not _needs_full_max_message(lenient):
            return lenient
        return strict
    if lenient_has_media:
        return lenient
    if strict_has_media:
        return strict
    return strict


async def _fetch_message_from_history(
    client: Any,
    chat_id: int,
    message_id: int,
) -> Any | None:
    try:
        history = await client.fetch_history(chat_id, backward=40)
    except Exception:
        logger.exception(
            "failed to fetch max history chat=%s msg=%s",
            chat_id,
            message_id,
        )
        return None

    for item in history or []:
        if int(getattr(item, "id", 0) or 0) == int(message_id):
            if item.chat_id is None:
                item.chat_id = chat_id
            return item
    return None


async def resolve_max_message(
    client: Any,
    message: Any,
    chat_id: int,
    *,
    sender: int | None = None,
    me_id: int | None = None,
) -> Any:
    if not _needs_full_max_message(message):
        logger.debug("max resolve skip fetch: %s", summarize_max_message(message))
        return message

    message_id = getattr(message, "id", None)
    if message_id is None:
        return message

    logger.info(
        "max resolve fetching full message chat=%s msg=%s before=%s",
        chat_id,
        message_id,
        summarize_max_message(message),
    )

    best_message = message
    for candidate_chat_id in _max_message_chat_ids(
        client,
        chat_id,
        sender=sender,
        me_id=me_id,
    ):
        try:
            full_message = await client.get_message(candidate_chat_id, int(message_id))
        except Exception:
            logger.exception(
                "failed to fetch max message chat=%s msg=%s",
                candidate_chat_id,
                message_id,
            )
            full_message = None

        if full_message is None:
            full_message = await _fetch_message_from_history(
                client,
                candidate_chat_id,
                int(message_id),
            )

        if full_message is None:
            continue

        if full_message.chat_id is None:
            full_message.chat_id = candidate_chat_id

        if not _needs_full_max_message(full_message):
            return full_message

        if extract_max_media_items(full_message) or find_audio_attachment(full_message) is not None:
            return full_message

        best_message = full_message

    logger.info(
        "max resolve done chat=%s msg=%s after=%s",
        chat_id,
        message_id,
        summarize_max_message(best_message),
    )
    return best_message


def max_message_attachment_types(message: Any) -> list[str]:
    return [_attachment_type_name(attach) for attach in _message_attaches(message)]


def _truncate_text(value: str, limit: int = 80) -> str:
    normalized = str(value or "").strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def summarize_max_message(message: Any) -> str:
    text = str(getattr(message, "text", "") or "")
    attach_types = max_message_attachment_types(message)
    media_items = extract_max_media_items(message)
    media_types = [item.message_type for item in media_items]
    has_audio = find_audio_attachment(message) is not None

    if media_types:
        kind = ",".join(media_types)
    elif has_audio:
        kind = "voice"
    elif attach_types:
        kind = f"unknown({','.join(attach_types)})"
    elif text.strip():
        kind = "text"
    else:
        kind = "empty"

    return (
        f"msg={getattr(message, 'id', None)} "
        f"chat={getattr(message, 'chat_id', None)} "
        f"sender={getattr(message, 'sender', None)} "
        f"kind={kind} "
        f"attaches={len(getattr(message, 'attaches', None) or [])} "
        f"types={attach_types or '-'} "
        f"media={media_types or '-'} "
        f"needs_full={_needs_full_max_message(message)} "
        f"text={_truncate_text(text)!r}"
    )


def summarize_max_payload(payload: dict[str, Any]) -> str:
    message_data = payload.get("message")
    if not isinstance(message_data, dict):
        message_data = payload

    message_id = message_data.get("id")
    chat_id = payload.get("chatId", payload.get("chat_id"))
    if chat_id is None:
        chat_id = message_data.get("chatId", message_data.get("chat_id"))

    attaches = _raw_payload_attaches(payload)
    attach_types = [_raw_attach_type(attach) for attach in attaches]
    text = str(message_data.get("text") or "")

    return (
        f"msg={message_id} chat={chat_id} "
        f"strict={strict_max_message_valid(payload)} "
        f"media_hint={payload_has_media_hint(payload)} "
        f"attaches={len(attaches)} types={attach_types or '-'} "
        f"text={_truncate_text(text, 60)!r}"
    )


def log_max_message_attachments(message: Any, *, account_id: str | None = None) -> None:
    prefix = f"account={account_id[:8]} " if account_id else ""
    for index, attach in enumerate(_message_attaches(message)):
        logger.debug(
            "max attach detail %sindex=%s type=%s photo_id=%s file_id=%s "
            "video_id=%s name=%s base_url=%s preview=%s",
            prefix,
            index,
            _attachment_type_name(attach),
            getattr(attach, "photo_id", None),
            getattr(attach, "file_id", None),
            getattr(attach, "video_id", None),
            getattr(attach, "name", None),
            bool(str(getattr(attach, "base_url", "") or "").strip()),
            bool(getattr(attach, "preview_data", None)),
        )


def classify_max_attachment(attach: Any) -> str | None:
    attach_type = _attachment_type_name(attach)
    if attach_type == "PHOTO" or int(getattr(attach, "photo_id", 0) or 0):
        return MESSAGE_TYPE_PHOTO
    if attach_type == "VIDEO":
        video_type = int(getattr(attach, "video_type", 0) or 0)
        if video_type == 1:
            return MESSAGE_TYPE_GIF
        return MESSAGE_TYPE_VIDEO
    if attach_type == "STICKER":
        return MESSAGE_TYPE_STICKER
    if attach_type == "FILE":
        filename = str(getattr(attach, "name", "") or "").strip().lower()
        if filename and any(filename.endswith(ext) for ext in IMAGE_EXTENSIONS):
            return MESSAGE_TYPE_PHOTO
        return MESSAGE_TYPE_DOCUMENT
    return None


def extract_max_media_items(message: Any) -> list[MaxMediaItem]:
    items: list[MaxMediaItem] = []
    for attach in _message_attaches(message):
        message_type = classify_max_attachment(attach)
        if message_type is None:
            continue
        filename = None
        if message_type == MESSAGE_TYPE_DOCUMENT:
            filename = str(getattr(attach, "name", "") or "").strip() or None
        items.append(
            MaxMediaItem(
                attachment=attach,
                message_type=message_type,
                filename=filename,
            )
        )
    return items


def max_media_text(
    *,
    caption: str,
    message_type: str,
    filename: str | None,
) -> str:
    normalized_caption = str(caption or "").strip()
    if normalized_caption:
        return normalized_caption
    if message_type == MESSAGE_TYPE_DOCUMENT and filename:
        return filename
    return media_placeholder_text(message_type)


def _upload_extension(
    content_type: str | None,
    filename: str | None,
    *,
    data: bytes | None = None,
    message_type: str | None = None,
) -> str:
    extension = guess_media_extension(content_type, filename)
    if extension != ".bin":
        return extension
    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix:
            return suffix
    if data:
        normalized_type = str(message_type or "").strip().lower()
        if normalized_type in {MESSAGE_TYPE_PHOTO, MESSAGE_TYPE_GIF}:
            return _guess_image_extension(data)
    return ".bin"


def _max_upload_filename(
    *,
    data: bytes,
    message_type: str,
    filename: str | None,
    content_type: str | None,
) -> str:
    extension = _upload_extension(
        content_type,
        filename,
        data=data,
        message_type=message_type,
    )
    if not extension.startswith("."):
        extension = f".{extension}"

    if filename:
        normalized = Path(filename).name.strip()
        if normalized and Path(normalized).suffix:
            return normalized
        if normalized:
            return f"{normalized}{extension}"

    normalized_type = str(message_type or "").strip().lower()
    if normalized_type == MESSAGE_TYPE_PHOTO:
        return f"image{extension}"
    if normalized_type == MESSAGE_TYPE_GIF:
        return f"image{extension}"
    if normalized_type == MESSAGE_TYPE_VIDEO:
        return f"video{extension}"
    return f"file{extension}"


def _client_proxy_url(client: Any) -> str | None:
    app = getattr(client, "_app", None)
    config = getattr(app, "config", None) if app else None
    proxy = getattr(config, "proxy", None) if config else None
    normalized = str(proxy or "").strip()
    return normalized or None


def _guess_image_extension(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:3] == b"GIF":
        return ".gif"
    return ".jpg"


def _photo_download_candidates(attach: Any) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(url: Any) -> None:
        normalized = str(url or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)

    for attr in ("base_url", "base_raw_url", "url"):
        add(getattr(attach, attr, None))

    base_url = str(getattr(attach, "base_url", "") or "").strip()
    base_raw_url = str(getattr(attach, "base_raw_url", "") or "").strip()
    photo_token = str(getattr(attach, "photo_token", "") or "").strip()
    photo_id = int(getattr(attach, "photo_id", 0) or 0)

    if photo_token.startswith("http://") or photo_token.startswith("https://"):
        add(photo_token)

    for root in (base_url, base_raw_url):
        if not root:
            continue
        if photo_token and photo_token not in root:
            add(f"{root.rstrip('/')}/{photo_token.lstrip('/')}")
            separator = "&" if "?" in root else "?"
            add(f"{root}{separator}token={photo_token}")
            add(f"{root}{separator}photoToken={photo_token}")
        if photo_id:
            add(f"{root.rstrip('/')}/{photo_id}")

    return urls


def _photo_has_download_source(attach: Any) -> bool:
    preview = getattr(attach, "preview_data", None)
    if isinstance(preview, (bytes, bytearray)) and len(preview) > 0:
        return True
    if _photo_download_candidates(attach):
        return True
    return bool(str(getattr(attach, "photo_token", "") or "").strip())


def _download_url(
    url: str,
    *,
    proxy: str | None = None,
    timeout: float = 25,
) -> tuple[bytes, str]:
    proxies = {"http": proxy, "https": proxy} if proxy else None
    response = requests.get(
        url,
        timeout=(5, timeout),
        headers=_MAX_DOWNLOAD_HEADERS,
        proxies=proxies,
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    extension = guess_media_extension(content_type, url)
    return response.content, extension


def _download_url_with_fallbacks(url: str, *, proxy: str | None = None) -> tuple[bytes, str]:
    last_error: Exception | None = None
    proxies_to_try: list[str | None] = [None]
    if proxy:
        proxies_to_try.append(proxy)

    for candidate_proxy in proxies_to_try:
        try:
            return _download_url(url, proxy=candidate_proxy)
        except Exception as exc:
            last_error = exc
            max_trace(
                "photo url attempt failed proxy=%s url=%s err=%s",
                bool(candidate_proxy),
                url[:120],
                exc,
            )
            logger.warning(
                "failed to download max photo url=%s proxy=%s: %s",
                url,
                bool(candidate_proxy),
                exc,
            )
    raise ValueError("max photo url download failed") from last_error


def _download_photo_attachment(attach: Any, *, proxy: str | None = None) -> tuple[bytes, str]:
    urls = _photo_download_candidates(attach)
    last_error: Exception | None = None
    for url in urls:
        try:
            data, extension = _download_url_with_fallbacks(url, proxy=proxy)
            if extension == ".bin":
                extension = _guess_image_extension(data)
            max_trace("photo download via url bytes=%s ext=%s", len(data), extension)
            return data, extension
        except Exception as exc:
            last_error = exc

    preview = getattr(attach, "preview_data", None)
    if isinstance(preview, (bytes, bytearray)) and len(preview) > 0:
        max_trace("photo download fallback preview bytes=%s", len(preview))
        return bytes(preview), _guess_image_extension(bytes(preview))

    raise ValueError("max photo download failed") from last_error


async def _refetch_photo_attachment(
    client: Any,
    chat_id: int,
    message_id: int,
) -> Any | None:
    try:
        full_message = await asyncio.wait_for(
            client.get_message(chat_id, message_id),
            timeout=10.0,
        )
    except Exception as exc:
        max_trace("photo refetch failed chat=%s msg=%s err=%s", chat_id, message_id, exc)
        logger.warning(
            "max photo refetch failed chat=%s msg=%s: %s",
            chat_id,
            message_id,
            exc,
        )
        return None

    for attach in _message_attaches(full_message):
        if classify_max_attachment(attach) == MESSAGE_TYPE_PHOTO:
            return attach
    return None


async def _download_max_photo(
    client: Any,
    attach: Any,
    *,
    chat_id: int | None,
    message_id: int | None,
    proxy: str | None,
) -> tuple[bytes, str]:
    candidates = _photo_download_candidates(attach)
    max_trace(
        "photo download start chat=%s msg=%s preview=%s urls=%s photo_id=%s base_url=%r",
        chat_id,
        message_id,
        bool(getattr(attach, "preview_data", None)),
        len(candidates),
        int(getattr(attach, "photo_id", 0) or 0),
        str(getattr(attach, "base_url", "") or "")[:120],
    )
    if candidates:
        max_trace("photo download candidates=%s", [url[:120] for url in candidates[:5]])

    last_error: Exception | None = None
    current_attach = attach
    for attempt in range(2):
        if attempt == 1:
            if chat_id is None or message_id is None:
                break
            refreshed = await _refetch_photo_attachment(client, int(chat_id), int(message_id))
            if refreshed is None:
                break
            current_attach = refreshed
            max_trace(
                "photo refetch ok chat=%s msg=%s urls=%s",
                chat_id,
                message_id,
                len(_photo_download_candidates(current_attach)),
            )

        try:
            return await asyncio.to_thread(
                _download_photo_attachment,
                current_attach,
                proxy=proxy,
            )
        except Exception as exc:
            last_error = exc
            max_trace("photo direct download failed attempt=%s err=%s", attempt + 1, exc)
            logger.warning(
                "max photo direct download failed attempt=%s: %s",
                attempt + 1,
                exc,
            )

    raise ValueError("max photo download failed") from last_error


async def _get_file_download_url(
    client: Any,
    chat_id: int,
    message_id: int,
    file_id: int,
    *,
    retries: int = 3,
    delay_sec: float = 0.5,
) -> str:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            file_request = await client.get_file_by_id(chat_id, message_id, file_id)
            if file_request is not None:
                url = str(getattr(file_request, "url", "") or "").strip()
                if url:
                    return url
            last_error = ValueError("max file download returned empty response")
        except Exception as exc:
            last_error = exc
            logger.warning(
                "max get_file_by_id attempt=%s chat=%s msg=%s file=%s: %s",
                attempt + 1,
                chat_id,
                message_id,
                file_id,
                exc,
            )
        if attempt + 1 < retries:
            await asyncio.sleep(delay_sec * (attempt + 1))
    raise ValueError("max file download failed") from last_error


async def download_max_media(
    client: Any,
    message: Any,
    item: MaxMediaItem,
    *,
    chat_id: int | None = None,
) -> tuple[bytes, str]:
    attach = item.attachment
    message_type = item.message_type
    proxy = _client_proxy_url(client)

    resolved_chat_id = chat_id if chat_id is not None else getattr(message, "chat_id", None)
    message_id = getattr(message, "id", None)

    if message_type == MESSAGE_TYPE_PHOTO:
        return await _download_max_photo(
            client,
            attach,
            chat_id=int(resolved_chat_id) if resolved_chat_id is not None else None,
            message_id=int(message_id) if message_id is not None else None,
            proxy=proxy,
        )

    if message_type == MESSAGE_TYPE_STICKER:
        url = str(getattr(attach, "url", "") or "").strip()
        if not url:
            raise ValueError("max sticker attachment has no url")
        return await asyncio.to_thread(_download_url, url, proxy=proxy)

    if resolved_chat_id is None or message_id is None:
        raise ValueError("max media message is missing chat_id or id")

    if message_type in {MESSAGE_TYPE_VIDEO, MESSAGE_TYPE_GIF}:
        video_id = int(getattr(attach, "video_id", 0) or 0)
        if not video_id:
            raise ValueError("max video attachment has no video_id")
        video_request = await client.get_video_by_id(resolved_chat_id, message_id, video_id)
        if video_request is None:
            raise ValueError("max video download returned empty response")
        url = str(getattr(video_request, "url", "") or "").strip()
        if not url:
            raise ValueError("max video download returned empty url")
        return await asyncio.to_thread(_download_url, url, proxy=proxy)

    if message_type == MESSAGE_TYPE_DOCUMENT:
        file_id = int(getattr(attach, "file_id", 0) or 0)
        if not file_id:
            raise ValueError("max file attachment has no file_id")
        url = await _get_file_download_url(
            client,
            int(resolved_chat_id),
            int(message_id),
            file_id,
        )
        data, extension = await asyncio.to_thread(
            _download_url_with_fallbacks,
            url,
            proxy=proxy,
        )
        if extension == ".bin" and item.filename:
            guessed = Path(item.filename).suffix
            if guessed:
                extension = guessed
        return data, extension

    raise ValueError(f"unsupported max media type: {message_type}")


async def send_max_media_message(
    client: Any,
    chat_id: int,
    *,
    data: bytes,
    message_type: str,
    filename: str | None = None,
    content_type: str | None = None,
    caption: str | None = None,
) -> Any:
    from pymax import File, Photo, Video
    from pymax.exceptions import UploadError

    normalized_type = str(message_type or "").strip().lower()
    trimmed_caption = str(caption or "").strip()
    upload_name = _max_upload_filename(
        data=data,
        message_type=normalized_type,
        filename=filename,
        content_type=content_type,
    )

    if normalized_type == MESSAGE_TYPE_PHOTO:
        attachment = Photo(raw=data, name=upload_name)
        try:
            return await client.send_message(
                chat_id=chat_id,
                text=trimmed_caption,
                attachments=[attachment],
            )
        except UploadError:
            logger.warning(
                "max photo upload failed, falling back to file chat=%s name=%s",
                chat_id,
                upload_name,
            )
            attachment = File(raw=data, name=upload_name)
            return await client.send_message(
                chat_id=chat_id,
                text=trimmed_caption,
                attachments=[attachment],
            )

    if normalized_type in {MESSAGE_TYPE_VIDEO, MESSAGE_TYPE_GIF}:
        extension = _upload_extension(
            content_type,
            filename,
            data=data,
            message_type=normalized_type,
        )
        if not extension.startswith("."):
            extension = f".{extension}"
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        try:
            attachment = Video(
                path=tmp_path,
                name=upload_name,
            )
            return await client.send_message(
                chat_id=chat_id,
                text=trimmed_caption,
                attachments=[attachment],
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    attachment = File(raw=data, name=upload_name)
    return await client.send_message(
        chat_id=chat_id,
        text=trimmed_caption,
        attachments=[attachment],
    )
