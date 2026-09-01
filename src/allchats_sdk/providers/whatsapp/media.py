from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neonize.aioze.client import NewAClient
from neonize.exc import SendMessageError

from allchats_sdk.providers.whatsapp.client import unwrap_whatsapp_message
from allchats_sdk.types.media import (
    MESSAGE_TYPE_DOCUMENT,
    MESSAGE_TYPE_GIF,
    MESSAGE_TYPE_PHOTO,
    MESSAGE_TYPE_STICKER,
    MESSAGE_TYPE_VIDEO,
    guess_media_extension,
    media_placeholder_text,
)
from allchats_sdk.types.voice import MESSAGE_TYPE_VOICE


@dataclass(slots=True)
class WhatsAppMediaInfo:
    message_type: str
    caption: str
    filename: str | None
    mime_type: str | None


def _part_mime(part: Any) -> str:
    return str(getattr(part, "mimetype", "") or getattr(part, "mimeType", "") or "").strip().lower()


def _part_caption(part: Any) -> str:
    return str(getattr(part, "caption", "") or "").strip()


def _part_filename(part: Any) -> str | None:
    name = str(getattr(part, "fileName", "") or getattr(part, "filename", "") or "").strip()
    return name or None


def detect_whatsapp_media_type(message: Any) -> str | None:
    if message is None:
        return None

    message = unwrap_whatsapp_message(message)

    audio = getattr(message, "audioMessage", None)
    if audio is not None:
        return MESSAGE_TYPE_VOICE

    sticker = getattr(message, "stickerMessage", None)
    if sticker is not None:
        return MESSAGE_TYPE_STICKER

    image = getattr(message, "imageMessage", None)
    if image is not None:
        return MESSAGE_TYPE_PHOTO

    video = getattr(message, "videoMessage", None)
    if video is not None:
        if bool(getattr(video, "gifPlayback", False)):
            return MESSAGE_TYPE_GIF
        mime = _part_mime(video)
        if mime == "image/gif":
            return MESSAGE_TYPE_GIF
        return MESSAGE_TYPE_VIDEO

    document = getattr(message, "documentMessage", None)
    if document is not None:
        mime = _part_mime(document)
        if mime == "image/gif":
            return MESSAGE_TYPE_GIF
        if mime.startswith("image/"):
            return MESSAGE_TYPE_PHOTO
        if mime.startswith("video/"):
            return MESSAGE_TYPE_VIDEO
        if mime.startswith("audio/"):
            return MESSAGE_TYPE_VOICE
        return MESSAGE_TYPE_DOCUMENT

    doc_with_caption = getattr(message, "documentWithCaptionMessage", None)
    if doc_with_caption is not None:
        inner = getattr(doc_with_caption, "message", None)
        if inner is not None:
            return detect_whatsapp_media_type(inner)

    return None


def whatsapp_media_info(message: Any) -> WhatsAppMediaInfo | None:
    message_type = detect_whatsapp_media_type(message)
    if message_type is None:
        return None

    part = None
    for field in ("audioMessage", "stickerMessage", "imageMessage", "videoMessage", "documentMessage"):
        candidate = getattr(message, field, None)
        if candidate is not None:
            part = candidate
            break

    if part is None:
        doc_with_caption = getattr(message, "documentWithCaptionMessage", None)
        if doc_with_caption is not None:
            inner = getattr(doc_with_caption, "message", None)
            if inner is not None:
                for field in ("documentMessage", "imageMessage", "videoMessage", "audioMessage"):
                    candidate = getattr(inner, field, None)
                    if candidate is not None:
                        part = candidate
                        break

    caption = _part_caption(part) if part is not None else ""
    filename = _part_filename(part) if part is not None else None
    mime_type = _part_mime(part) if part is not None else None
    return WhatsAppMediaInfo(
        message_type=message_type,
        caption=caption,
        filename=filename,
        mime_type=mime_type,
    )


def whatsapp_voice_duration_ms(message: Any) -> int | None:
    message = unwrap_whatsapp_message(message)
    audio = getattr(message, "audioMessage", None)
    if audio is None:
        return None
    try:
        seconds = int(getattr(audio, "seconds", 0) or 0)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return seconds * 1000


def whatsapp_media_text(
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


async def download_whatsapp_media(client: NewAClient, message: Any) -> tuple[bytes, str]:
    data = await client.download_any(message)
    if not data:
        raise ValueError("whatsapp media download returned empty data")

    info = whatsapp_media_info(message)
    extension = guess_media_extension(
        info.mime_type if info else None,
        info.filename if info else None,
    )
    return data, extension


def _parse_send_response_id(response: Any) -> str:
    message_id = str(getattr(response, "ID", "") or getattr(response, "id", "") or "").strip()
    if message_id:
        return message_id
    send_response = getattr(response, "SendResponse", None)
    if send_response is not None:
        message_id = str(getattr(send_response, "ID", "") or "").strip()
        if message_id:
            return message_id
    return ""


async def send_whatsapp_media_message(
    client: NewAClient,
    jid: Any,
    *,
    data: bytes,
    message_type: str,
    filename: str | None = None,
    content_type: str | None = None,
    caption: str | None = None,
) -> str:
    trimmed_caption = str(caption or "").strip() or None
    normalized_type = str(message_type or "").strip().lower()

    try:
        if normalized_type == MESSAGE_TYPE_PHOTO:
            response = await client.send_image(jid, data, caption=trimmed_caption)
        elif normalized_type == MESSAGE_TYPE_GIF:
            response = await client.send_video(
                jid,
                data,
                caption=trimmed_caption,
                gifplayback=True,
                is_gif=True,
            )
        elif normalized_type == MESSAGE_TYPE_VIDEO:
            response = await client.send_video(jid, data, caption=trimmed_caption)
        elif normalized_type == MESSAGE_TYPE_STICKER:
            response = await client.send_sticker(jid, data, passthrough=True)
        else:
            response = await client.send_document(
                jid,
                data,
                caption=trimmed_caption,
                filename=filename,
                mimetype=content_type,
            )
    except SendMessageError:
        raise
    except Exception as exc:
        raise SendMessageError(str(exc)) from exc

    message_id = _parse_send_response_id(response)
    if not message_id:
        raise SendMessageError("whatsapp media send succeeded without message id")
    return message_id
