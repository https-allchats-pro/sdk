from __future__ import annotations

from pathlib import Path

MESSAGE_TYPE_PHOTO = "photo"
MESSAGE_TYPE_VIDEO = "video"
MESSAGE_TYPE_GIF = "gif"
MESSAGE_TYPE_STICKER = "sticker"
MESSAGE_TYPE_DOCUMENT = "document"

PHOTO_MESSAGE_TEXT = "[photo]"
VIDEO_MESSAGE_TEXT = "[video]"
GIF_MESSAGE_TEXT = "[gif]"
STICKER_MESSAGE_TEXT = "[sticker]"
DOCUMENT_MESSAGE_TEXT = "[document]"
ALBUM_MESSAGE_TEXT = "[album]"

IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
}

VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-msvideo",
    "video/mpeg",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".avi", ".mkv", ".mpeg", ".mpg"}
DOCUMENT_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".zip", ".rar", ".7z", ".tar", ".gz",
}

MEDIA_PLACEHOLDERS = {
    MESSAGE_TYPE_PHOTO: PHOTO_MESSAGE_TEXT,
    MESSAGE_TYPE_VIDEO: VIDEO_MESSAGE_TEXT,
    MESSAGE_TYPE_GIF: GIF_MESSAGE_TEXT,
    MESSAGE_TYPE_STICKER: STICKER_MESSAGE_TEXT,
    MESSAGE_TYPE_DOCUMENT: DOCUMENT_MESSAGE_TEXT,
}


def is_photo_message_type(message_type: str | None) -> bool:
    return str(message_type or "").strip().lower() == MESSAGE_TYPE_PHOTO


def is_video_message_type(message_type: str | None) -> bool:
    return str(message_type or "").strip().lower() == MESSAGE_TYPE_VIDEO


def is_gif_message_type(message_type: str | None) -> bool:
    return str(message_type or "").strip().lower() == MESSAGE_TYPE_GIF


def is_sticker_message_type(message_type: str | None) -> bool:
    return str(message_type or "").strip().lower() == MESSAGE_TYPE_STICKER


def is_document_message_type(message_type: str | None) -> bool:
    return str(message_type or "").strip().lower() == MESSAGE_TYPE_DOCUMENT


def is_media_message_type(message_type: str | None) -> bool:
    normalized = str(message_type or "").strip().lower()
    return normalized in MEDIA_PLACEHOLDERS


def is_visual_media_message_type(message_type: str | None) -> bool:
    normalized = str(message_type or "").strip().lower()
    return normalized in {
        MESSAGE_TYPE_PHOTO,
        MESSAGE_TYPE_VIDEO,
        MESSAGE_TYPE_GIF,
        MESSAGE_TYPE_STICKER,
    }


def is_placeholder_text(text: str | None) -> bool:
    normalized = str(text or "").strip()
    return normalized in set(MEDIA_PLACEHOLDERS.values()) | {ALBUM_MESSAGE_TEXT}


def media_placeholder_text(message_type: str) -> str:
    return MEDIA_PLACEHOLDERS.get(str(message_type or "").strip().lower(), PHOTO_MESSAGE_TEXT)


def guess_media_extension(mime_type: str | None, filename: str | None = None) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if normalized == "image/png":
        return ".png"
    if normalized == "image/webp":
        return ".webp"
    if normalized == "image/gif":
        return ".gif"
    if normalized == "video/mp4":
        return ".mp4"
    if normalized == "video/quicktime":
        return ".mov"
    if normalized == "video/webm":
        return ".webm"
    if normalized == "video/x-msvideo":
        return ".avi"
    if normalized == "application/pdf":
        return ".pdf"
    if normalized in {"application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}:
        return ".docx"
    if normalized == "text/plain":
        return ".txt"
    if normalized == "application/zip":
        return ".zip"
    if normalized == "text/markdown":
        return ".md"

    if filename:
        lowered = filename.lower()
        for ext in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | DOCUMENT_EXTENSIONS:
            if lowered.endswith(ext):
                return ext
        suffix = Path(lowered).suffix
        if suffix:
            return suffix
    return ".bin"


def media_type_from_upload(mime_type: str | None, filename: str | None = None) -> str:
    normalized = str(mime_type or "").strip().lower()
    if normalized in VIDEO_MIME_TYPES or normalized.startswith("video/"):
        return MESSAGE_TYPE_VIDEO
    if normalized == "image/gif":
        return MESSAGE_TYPE_GIF
    if normalized in IMAGE_MIME_TYPES or normalized.startswith("image/"):
        return MESSAGE_TYPE_PHOTO

    if filename:
        lowered = filename.lower()
        for ext in VIDEO_EXTENSIONS:
            if lowered.endswith(ext):
                return MESSAGE_TYPE_VIDEO
        if lowered.endswith(".gif"):
            return MESSAGE_TYPE_GIF
        for ext in IMAGE_EXTENSIONS - {".gif"}:
            if lowered.endswith(ext):
                return MESSAGE_TYPE_PHOTO
        for ext in DOCUMENT_EXTENSIONS:
            if lowered.endswith(ext):
                return MESSAGE_TYPE_DOCUMENT
    if normalized.startswith("application/") or normalized.startswith("text/"):
        return MESSAGE_TYPE_DOCUMENT
    return MESSAGE_TYPE_DOCUMENT
