from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from allchats_sdk.types.media import (
    MESSAGE_TYPE_DOCUMENT,
    MESSAGE_TYPE_GIF,
    MESSAGE_TYPE_PHOTO,
    MESSAGE_TYPE_STICKER,
    MESSAGE_TYPE_VIDEO,
    guess_media_extension,
    media_placeholder_text,
)


def _document_attributes(message: Any) -> list[Any]:
    document = getattr(message, "document", None)
    if document is None:
        return []
    return list(getattr(document, "attributes", []) or [])


def _is_voice_document(message: Any) -> bool:
    from telethon.tl.types import DocumentAttributeAudio

    for attribute in _document_attributes(message):
        if isinstance(attribute, DocumentAttributeAudio) and getattr(attribute, "voice", False):
            return True
    return False


def detect_telegram_media_type(message: Any) -> str | None:
    if getattr(message, "photo", None):
        return MESSAGE_TYPE_PHOTO
    if getattr(message, "video", None) or getattr(message, "video_note", None):
        return MESSAGE_TYPE_VIDEO
    if getattr(message, "sticker", False):
        return MESSAGE_TYPE_STICKER

    document = getattr(message, "document", None)
    if document is None:
        return None
    if _is_voice_document(message):
        return None

    from telethon.tl.types import DocumentAttributeAnimated, DocumentAttributeSticker

    attributes = _document_attributes(message)
    if any(isinstance(attribute, DocumentAttributeAnimated) for attribute in attributes):
        return MESSAGE_TYPE_GIF
    if any(isinstance(attribute, DocumentAttributeSticker) for attribute in attributes):
        return MESSAGE_TYPE_STICKER

    mime = str(getattr(document, "mime_type", "") or "").strip().lower()
    if mime == "image/gif":
        return MESSAGE_TYPE_GIF
    if mime.startswith("image/"):
        return MESSAGE_TYPE_PHOTO
    if mime.startswith("video/"):
        return MESSAGE_TYPE_VIDEO
    return MESSAGE_TYPE_DOCUMENT


def telegram_media_filename(message: Any) -> str | None:
    from telethon.tl.types import DocumentAttributeFilename

    for attribute in _document_attributes(message):
        if isinstance(attribute, DocumentAttributeFilename):
            name = str(getattr(attribute, "file_name", "") or "").strip()
            if name:
                return name
    return None


def telegram_grouped_id(message: Any) -> int | None:
    value = getattr(message, "grouped_id", None)
    if value:
        return int(value)
    return None


def telegram_media_text(message: Any, message_type: str) -> str:
    caption = str(getattr(message, "message", "") or "").strip()
    if caption:
        return caption
    if message_type == MESSAGE_TYPE_DOCUMENT:
        filename = telegram_media_filename(message)
        if filename:
            return filename
    return media_placeholder_text(message_type)


async def download_telegram_media(client: Any, message: Any) -> tuple[bytes, str]:
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        saved = await client.download_media(message, file=tmp_path)
        path = Path(saved or tmp_path)
        data = path.read_bytes()
        extension = path.suffix or ".jpg"
        return data, extension
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@dataclass(slots=True)
class TelegramMediaUpload:
    data: bytes
    extension: str
    message_type: str


async def send_telegram_media(
    client: Any,
    peer: Any,
    *,
    uploads: list[TelegramMediaUpload],
    caption: str | None = None,
) -> Any:
    if not uploads:
        raise ValueError("uploads are required")

    temp_paths: list[str] = []
    try:
        for upload in uploads:
            ext = upload.extension if upload.extension.startswith(".") else f".{upload.extension}"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(upload.data)
                temp_paths.append(tmp.name)

        kwargs: dict[str, Any] = {}
        if caption:
            kwargs["caption"] = caption

        if len(temp_paths) == 1:
            upload = uploads[0]
            if upload.message_type == MESSAGE_TYPE_VIDEO:
                kwargs["supports_streaming"] = True
            if upload.message_type == MESSAGE_TYPE_DOCUMENT:
                kwargs["force_document"] = True
            return await client.send_file(peer, temp_paths[0], **kwargs)

        return await client.send_file(peer, temp_paths, **kwargs)
    finally:
        for path in temp_paths:
            Path(path).unlink(missing_ok=True)


def extension_from_upload(filename: str | None, content_type: str | None) -> str:
    return guess_media_extension(content_type, filename)
