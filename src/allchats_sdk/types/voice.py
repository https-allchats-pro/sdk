"""Shared voice message-type constants and helpers."""

from __future__ import annotations

MESSAGE_TYPE_TEXT = "text"
MESSAGE_TYPE_VOICE = "voice"
VOICE_MESSAGE_TEXT = "[voice]"

VOICE_MIME_TYPES = {
    "audio/ogg",
    "audio/opus",
    "audio/webm",
    "audio/mpeg",
    "audio/mp4",
    "audio/aac",
    "audio/wav",
    "application/ogg",
}

VOICE_EXTENSIONS = {".ogg", ".opus", ".webm", ".mp3", ".m4a", ".wav"}


def is_voice_message_type(message_type: str | None) -> bool:
    return str(message_type or "").strip().lower() == MESSAGE_TYPE_VOICE


def is_voice_placeholder_text(text: str | None) -> bool:
    return str(text or "").strip() == VOICE_MESSAGE_TEXT


def guess_voice_extension(mime_type: str | None, filename: str | None = None) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized in {"audio/ogg", "application/ogg"}:
        return ".ogg"
    if normalized == "audio/opus":
        return ".opus"
    if normalized == "audio/webm":
        return ".webm"
    if normalized in {"audio/mpeg", "audio/mp3"}:
        return ".mp3"
    if normalized in {"audio/mp4", "audio/aac"}:
        return ".m4a"
    if normalized == "audio/wav":
        return ".wav"

    if filename:
        lowered = filename.lower()
        for ext in VOICE_EXTENSIONS:
            if lowered.endswith(ext):
                return ext
    return ".ogg"


def media_api_path(account_id: str, message_id: str) -> str:
    return f"/api/accounts/{account_id}/messages/{message_id}/media"
