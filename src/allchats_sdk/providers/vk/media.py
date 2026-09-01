from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from allchats_sdk.providers.vk.native_api import USER_AGENT, VkNativeApiError, vk_method
from allchats_sdk.providers.vk.voice import download_voice_from_url
from allchats_sdk.types.media import (
    MESSAGE_TYPE_DOCUMENT,
    MESSAGE_TYPE_GIF,
    MESSAGE_TYPE_PHOTO,
    MESSAGE_TYPE_STICKER,
    MESSAGE_TYPE_VIDEO,
    media_placeholder_text,
)

logger = logging.getLogger(__name__)

VK_DOC_TYPE_GIF = 3
VK_DOC_TYPE_IMAGE = 4
VK_DOC_TYPE_AUDIO = 5
VK_DOC_TYPE_VIDEO = 6


@dataclass(slots=True)
class VkMediaAttachment:
    message_type: str
    download_url: str
    filename: str | None = None
    extension_hint: str | None = None


@dataclass(slots=True)
class VkPreparedUpload:
    data: bytes
    filename: str
    message_type: str
    extension: str


def _is_voice_doc(doc: dict[str, Any]) -> bool:
    return int(doc.get("type") or 0) == VK_DOC_TYPE_AUDIO


def _best_photo_url(photo: dict[str, Any]) -> str | None:
    sizes = photo.get("sizes")
    if isinstance(sizes, list) and sizes:
        best = max(
            (item for item in sizes if isinstance(item, dict)),
            key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0),
            default=None,
        )
        if best is not None:
            url = str(best.get("url") or "").strip()
            if url:
                return url
    for key in ("photo_2560", "photo_1280", "photo_807", "photo_604", "photo_130", "photo_75"):
        url = str(photo.get(key) or "").strip()
        if url:
            return url
    url = str(photo.get("url") or "").strip()
    return url or None


def _best_sticker_url(sticker: dict[str, Any]) -> str | None:
    for images_key in ("images", "images_with_background"):
        images = sticker.get(images_key)
        if not isinstance(images, list):
            continue
        candidates = [item for item in images if isinstance(item, dict)]
        if not candidates:
            continue
        best = max(
            candidates,
            key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0),
        )
        url = str(best.get("url") or "").strip()
        if url:
            return url
    return None


def _video_download_url(video: dict[str, Any]) -> str | None:
    files = video.get("files")
    if isinstance(files, dict):
        for key in ("mp4_1080", "mp4_720", "mp4_480", "mp4_360", "mp4_240", "external"):
            url = str(files.get(key) or "").strip()
            if url:
                return url
    for key in ("direct_link", "player", "share_url"):
        url = str(video.get(key) or "").strip()
        if url and url.startswith("http"):
            return url
    return None


def _doc_message_type(doc: dict[str, Any]) -> str:
    doc_type = int(doc.get("type") or 0)
    if doc_type == VK_DOC_TYPE_GIF:
        return MESSAGE_TYPE_GIF
    if doc_type == VK_DOC_TYPE_IMAGE:
        return MESSAGE_TYPE_PHOTO
    if doc_type == VK_DOC_TYPE_VIDEO:
        return MESSAGE_TYPE_VIDEO
    return MESSAGE_TYPE_DOCUMENT


def _extension_from_url(url: str, fallback: str = ".bin") -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".webm", ".pdf", ".doc", ".docx", ".zip"):
        if path.endswith(ext):
            return ext
    return fallback


def detect_vk_attachment_type(attachment: dict[str, Any]) -> str | None:
    attach_type = str(attachment.get("type") or "").strip().lower()
    if attach_type == "photo":
        return MESSAGE_TYPE_PHOTO
    if attach_type == "video":
        return MESSAGE_TYPE_VIDEO
    if attach_type == "sticker":
        return MESSAGE_TYPE_STICKER
    if attach_type == "doc":
        doc = attachment.get("doc")
        if isinstance(doc, dict) and not _is_voice_doc(doc):
            return _doc_message_type(doc)
    return None


def extract_vk_media_attachments(message: dict[str, Any]) -> list[VkMediaAttachment]:
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return []

    items: list[VkMediaAttachment] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attach_type = str(attachment.get("type") or "").strip().lower()
        if attach_type == "audio_message":
            continue

        if attach_type == "photo":
            photo = attachment.get("photo")
            if isinstance(photo, dict):
                url = _best_photo_url(photo)
                if url:
                    items.append(VkMediaAttachment(
                        message_type=MESSAGE_TYPE_PHOTO,
                        download_url=url,
                        extension_hint=_extension_from_url(url, ".jpg"),
                    ))
            continue

        if attach_type == "video":
            video = attachment.get("video")
            if isinstance(video, dict):
                url = _video_download_url(video)
                if url:
                    title = str(video.get("title") or "").strip() or None
                    items.append(VkMediaAttachment(
                        message_type=MESSAGE_TYPE_VIDEO,
                        download_url=url,
                        filename=title,
                        extension_hint=_extension_from_url(url, ".mp4"),
                    ))
            continue

        if attach_type == "sticker":
            sticker = attachment.get("sticker")
            if isinstance(sticker, dict):
                url = _best_sticker_url(sticker)
                if url:
                    items.append(VkMediaAttachment(
                        message_type=MESSAGE_TYPE_STICKER,
                        download_url=url,
                        extension_hint=_extension_from_url(url, ".webp"),
                    ))
            continue

        if attach_type == "doc":
            doc = attachment.get("doc")
            if not isinstance(doc, dict) or _is_voice_doc(doc):
                continue
            url = str(doc.get("url") or "").strip()
            if not url:
                continue
            filename = str(doc.get("title") or doc.get("ext") or "").strip() or None
            message_type = _doc_message_type(doc)
            items.append(VkMediaAttachment(
                message_type=message_type,
                download_url=url,
                filename=filename,
                extension_hint=_extension_from_url(url, ".bin"),
            ))

    return items


def vk_media_text(*, caption: str, message_type: str, filename: str | None) -> str:
    if caption.strip():
        return caption.strip()
    if message_type == MESSAGE_TYPE_DOCUMENT and filename:
        return filename
    return media_placeholder_text(message_type)


def download_vk_media(url: str, *, access_token: str) -> bytes:
    return download_voice_from_url(url, access_token=access_token)


def _format_photo_attachment(photo: dict[str, Any]) -> str:
    owner_id = int(photo.get("owner_id") or 0)
    photo_id = int(photo.get("id") or 0)
    if not owner_id or not photo_id:
        raise VkNativeApiError("vk photo save returned invalid id")
    access_key = str(photo.get("access_key") or "").strip()
    if access_key:
        return f"photo{owner_id}_{photo_id}_{access_key}"
    return f"photo{owner_id}_{photo_id}"


def _format_doc_attachment(doc: dict[str, Any]) -> str:
    owner_id = int(doc.get("owner_id") or 0)
    doc_id = int(doc.get("id") or 0)
    if not owner_id or not doc_id:
        raise VkNativeApiError("vk docs.save returned invalid doc id")
    access_key = str(doc.get("access_key") or "").strip()
    if access_key:
        return f"doc{owner_id}_{doc_id}_{access_key}"
    return f"doc{owner_id}_{doc_id}"


def _parse_saved_doc(saved: Any) -> dict[str, Any]:
    if isinstance(saved, dict):
        doc = saved.get("doc")
        if isinstance(doc, list) and doc and isinstance(doc[0], dict):
            return doc[0]
        if isinstance(doc, dict):
            return doc
    if isinstance(saved, list) and saved and isinstance(saved[0], dict):
        return saved[0]
    raise VkNativeApiError("vk docs.save returned invalid payload")


def _parse_saved_photo(saved: Any) -> dict[str, Any]:
    if isinstance(saved, list) and saved and isinstance(saved[0], dict):
        return saved[0]
    if isinstance(saved, dict):
        return saved
    raise VkNativeApiError("vk photos.saveMessagesPhoto returned invalid payload")


def _guess_upload_content_type(filename: str, message_type: str) -> str:
    lowered = filename.lower()
    if message_type == MESSAGE_TYPE_PHOTO or lowered.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "image/jpeg"
    if message_type == MESSAGE_TYPE_VIDEO or lowered.endswith((".mp4", ".mov", ".webm")):
        return "video/mp4"
    if message_type == MESSAGE_TYPE_GIF or lowered.endswith(".gif"):
        return "image/gif"
    return "application/octet-stream"


def upload_vk_photo(
    *,
    access_token: str,
    peer_id: int,
    data: bytes,
    filename: str,
) -> str:
    upload_server = vk_method(
        "photos.getMessagesUploadServer",
        access_token=access_token,
        peer_id=peer_id,
    )
    upload_url = str(upload_server.get("upload_url") or "").strip()
    if not upload_url:
        raise VkNativeApiError("vk photo upload_url is missing")

    upload_response = requests.post(
        upload_url,
        files={"photo": (filename, data, _guess_upload_content_type(filename, MESSAGE_TYPE_PHOTO))},
        headers={"User-Agent": USER_AGENT},
        timeout=120,
    )
    upload_response.raise_for_status()
    try:
        uploaded = upload_response.json()
    except ValueError as exc:
        raise VkNativeApiError("vk photo upload returned invalid json") from exc
    if not isinstance(uploaded, dict):
        raise VkNativeApiError("vk photo upload returned invalid payload")

    saved = vk_method(
        "photos.saveMessagesPhoto",
        access_token=access_token,
        server=uploaded.get("server"),
        photo=uploaded.get("photo"),
        hash=uploaded.get("hash"),
    )
    photo = _parse_saved_photo(saved)
    return _format_photo_attachment(photo)


def upload_vk_document(
    *,
    access_token: str,
    peer_id: int,
    data: bytes,
    filename: str,
    message_type: str,
) -> str:
    upload_server = vk_method(
        "docs.getMessagesUploadServer",
        access_token=access_token,
        type="doc",
        peer_id=peer_id,
    )
    upload_url = str(upload_server.get("upload_url") or "").strip()
    if not upload_url:
        raise VkNativeApiError("vk document upload_url is missing")

    upload_response = requests.post(
        upload_url,
        files={"file": (filename, data, _guess_upload_content_type(filename, message_type))},
        headers={"User-Agent": USER_AGENT},
        timeout=120,
    )
    upload_response.raise_for_status()
    try:
        uploaded = upload_response.json()
    except ValueError as exc:
        raise VkNativeApiError("vk document upload returned invalid json") from exc
    if not isinstance(uploaded, dict) or not uploaded.get("file"):
        raise VkNativeApiError(f"vk document upload failed: {uploaded!r}")

    saved = vk_method(
        "docs.save",
        access_token=access_token,
        file=uploaded["file"],
        title=filename,
    )
    doc = _parse_saved_doc(saved)
    return _format_doc_attachment(doc)


def upload_vk_media_attachment(
    *,
    access_token: str,
    peer_id: int,
    data: bytes,
    filename: str,
    message_type: str,
) -> str:
    if message_type == MESSAGE_TYPE_PHOTO:
        return upload_vk_photo(
            access_token=access_token,
            peer_id=peer_id,
            data=data,
            filename=filename,
        )
    return upload_vk_document(
        access_token=access_token,
        peer_id=peer_id,
        data=data,
        filename=filename,
        message_type=message_type,
    )


def send_vk_message_with_attachments(
    *,
    access_token: str,
    peer_id: int,
    attachments: list[str],
    caption: str | None = None,
    random_id: int | None = None,
) -> int:
    if not attachments:
        raise VkNativeApiError("vk attachments are required")
    resolved_random_id = random_id if random_id is not None else random.randint(1, 2_000_000_000)
    params: dict[str, Any] = {
        "peer_id": peer_id,
        "random_id": resolved_random_id,
        "attachment": ",".join(attachments),
    }
    if caption and caption.strip():
        params["message"] = caption.strip()
    message_id = vk_method(
        "messages.send",
        access_token=access_token,
        **params,
    )
    return int(message_id)
