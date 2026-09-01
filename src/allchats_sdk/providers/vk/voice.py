from __future__ import annotations

import logging
import random
from typing import Any
from urllib.parse import urlparse

import requests

from allchats_sdk.providers.vk.native_api import USER_AGENT, VkNativeApiError, vk_method

logger = logging.getLogger(__name__)


def get_message_by_id(*, access_token: str, peer_id: int, message_id: int) -> dict[str, Any] | None:
    del peer_id  # kept for callers; VK getById uses global message id
    response = vk_method(
        "messages.getById",
        access_token=access_token,
        message_ids=str(message_id),
        extended=1,
    )
    items = response.get("items") if isinstance(response, dict) else response
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return None


def _duration_ms_from_seconds(duration: Any) -> int | None:
    if isinstance(duration, int) and duration > 0:
        return duration * 1000
    return None


def _voice_url_from_audio_message(audio: dict[str, Any]) -> tuple[str | None, int | None]:
    url = str(audio.get("link_ogg") or audio.get("link_mp3") or audio.get("url") or "").strip()
    if not url:
        return None, None
    return url, _duration_ms_from_seconds(audio.get("duration"))


def extract_voice_download_url(message: dict[str, Any]) -> tuple[str, int | None] | None:
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return None

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("type") == "audio_message":
            audio = attachment.get("audio_message")
            if isinstance(audio, dict):
                url, duration_ms = _voice_url_from_audio_message(audio)
                if url:
                    return url, duration_ms
        if attachment.get("type") == "doc":
            doc = attachment.get("doc")
            if not isinstance(doc, dict):
                continue
            if int(doc.get("type") or 0) != 5:
                continue
            url = str(doc.get("url") or doc.get("link_ogg") or doc.get("link_mp3") or "").strip()
            if url:
                return url, _duration_ms_from_seconds(doc.get("duration"))
    return None


def guess_voice_extension_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".mp3"):
        return ".mp3"
    if path.endswith(".ogg") or path.endswith(".opus"):
        return ".ogg"
    if ".mp3" in url.lower():
        return ".mp3"
    return ".ogg"


def download_voice_from_url(url: str, *, access_token: str | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    response = requests.get(url, headers=headers, timeout=60)
    if response.status_code in {401, 403} and access_token:
        response = requests.get(
            url,
            headers=headers,
            params={"access_token": access_token},
            timeout=60,
        )
    response.raise_for_status()
    if not response.content:
        raise VkNativeApiError("vk voice download returned empty body")
    return response.content


def _parse_saved_doc(saved: Any) -> dict[str, Any]:
    if isinstance(saved, dict):
        audio_message = saved.get("audio_message")
        if isinstance(audio_message, dict):
            return audio_message
        doc = saved.get("doc")
        if isinstance(doc, list) and doc and isinstance(doc[0], dict):
            return doc[0]
        if isinstance(doc, dict):
            return doc
    if isinstance(saved, list) and saved and isinstance(saved[0], dict):
        return saved[0]
    raise VkNativeApiError("vk docs.save returned invalid payload")


def _format_doc_attachment(doc: dict[str, Any]) -> str:
    owner_id = int(doc.get("owner_id") or 0)
    doc_id = int(doc.get("id") or 0)
    if not owner_id or not doc_id:
        raise VkNativeApiError("vk docs.save returned invalid doc id")
    access_key = str(doc.get("access_key") or "").strip()
    if access_key:
        return f"doc{owner_id}_{doc_id}_{access_key}"
    return f"doc{owner_id}_{doc_id}"


def upload_voice_message(
    *,
    access_token: str,
    peer_id: int,
    data: bytes,
    filename: str = "voice.ogg",
) -> str:
    upload_server = vk_method(
        "docs.getMessagesUploadServer",
        access_token=access_token,
        type="audio_message",
        peer_id=peer_id,
    )
    upload_url = str(upload_server.get("upload_url") or "").strip()
    if not upload_url:
        raise VkNativeApiError("vk upload_url is missing")

    normalized_name = filename if filename.lower().endswith(".ogg") else "voice.ogg"
    upload_response = requests.post(
        upload_url,
        files={"file": (normalized_name, data, "audio/ogg")},
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    upload_response.raise_for_status()
    try:
        uploaded = upload_response.json()
    except ValueError as exc:
        raise VkNativeApiError("vk voice upload returned invalid json") from exc

    if not isinstance(uploaded, dict) or not uploaded.get("file"):
        logger.warning("vk voice upload rejected payload=%s", uploaded)
        raise VkNativeApiError(f"vk voice upload failed: {uploaded!r}")

    saved = vk_method(
        "docs.save",
        access_token=access_token,
        file=uploaded["file"],
        title="Voice message",
    )
    doc = _parse_saved_doc(saved)
    return _format_doc_attachment(doc)


def send_voice_message(
    *,
    access_token: str,
    peer_id: int,
    data: bytes,
    filename: str = "voice.ogg",
    random_id: int | None = None,
) -> int:
    attachment = upload_voice_message(
        access_token=access_token,
        peer_id=peer_id,
        data=data,
        filename=filename,
    )
    resolved_random_id = random_id if random_id is not None else random.randint(1, 2_000_000_000)
    message_id = vk_method(
        "messages.send",
        access_token=access_token,
        peer_id=peer_id,
        random_id=resolved_random_id,
        attachment=attachment,
    )
    return int(message_id)


def parse_longpoll_has_voice_hint(extra_values: dict[str, Any]) -> bool:
    for key, value in extra_values.items():
        key_str = str(key)
        if not key_str.startswith("attach"):
            continue
        value_str = str(value).strip().lower()
        if value_str in {"audio_message", "audiomsg"}:
            return True
        # Classic LP: attachN_type=doc + attachN_kind=audiomsg
        if key_str.endswith("_kind") and value_str in {"audiomsg", "audio_message"}:
            return True
        if key_str.endswith("_type") and value_str == "doc":
            kind = str(
                extra_values.get(key_str.replace("_type", "_kind"))
                or extra_values.get(f"{key_str[:-5]}_kind")
                or ""
            ).strip().lower()
            if kind in {"audiomsg", "audio_message", ""}:
                # Empty kind: still treat doc attach as possible voice; full fetch decides.
                return True
    return False


def parse_longpoll_has_attachments(extra_values: dict[str, Any]) -> bool:
    return any(
        str(key).startswith("attach") or str(key) in {"geo", "fwd", "reply", "attachments"}
        for key in extra_values
    )
