from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from allchats_sdk.types.audio_convert import prepare_telegram_voice_bytes
from allchats_sdk.types.voice import (
    MESSAGE_TYPE_VOICE,
    VOICE_MESSAGE_TEXT,
    guess_voice_extension,
)

logger = logging.getLogger(__name__)


def is_telegram_voice_message(message: Any) -> bool:
    return bool(getattr(message, "voice", False))


async def download_telegram_voice(client: Any, message: Any) -> tuple[bytes, str, int | None]:
    from telethon.tl.types import DocumentAttributeAudio

    duration_ms: int | None = None
    document = getattr(message, "document", None)
    if document is not None:
        for attribute in getattr(document, "attributes", []) or []:
            if isinstance(attribute, DocumentAttributeAudio):
                duration_ms = int(attribute.duration or 0) * 1000
                break

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        saved = await client.download_media(message, file=tmp_path)
        path = Path(saved or tmp_path)
        data = path.read_bytes()
        extension = path.suffix or ".ogg"
        return data, extension, duration_ms
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def send_telegram_voice(
    client: Any,
    peer: Any,
    *,
    data: bytes,
    extension: str,
    duration_ms: int | None = None,
) -> Any:
    _ = duration_ms
    voice_data, voice_ext = await prepare_telegram_voice_bytes(data, extension)
    with tempfile.NamedTemporaryFile(suffix=voice_ext, delete=False) as tmp:
        tmp.write(voice_data)
        tmp_path = tmp.name
    try:
        return await client.send_file(
            peer,
            tmp_path,
            voice_note=True,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def voice_message_fields(
    *,
    data: bytes,
    extension: str,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    _ = data, extension
    return {
        "text": VOICE_MESSAGE_TEXT,
        "message_type": MESSAGE_TYPE_VOICE,
        "duration_ms": duration_ms,
    }


def extension_from_upload(filename: str | None, content_type: str | None) -> str:
    return guess_voice_extension(content_type, filename)
