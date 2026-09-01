from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp
import requests
import soundfile as sf
from PIL import Image, ImageDraw
from pydantic import ValidationError

from allchats_sdk.providers.max.media import (
    audio_duration_ms,
    find_audio_attachment,
)
from allchats_sdk.providers.max.trace import max_trace
from allchats_sdk.types.voice import MESSAGE_TYPE_VOICE, VOICE_MESSAGE_TEXT

logger = logging.getLogger(__name__)

__all__ = [
    "audio_duration_ms",
    "download_max_voice",
    "find_audio_attachment",
    "send_max_voice",
    "voice_message_fields",
]

_WAVE_BARS = 64
_WAVE_WIDTH = 256
_WAVE_HEIGHT = 48


def download_max_voice(attach: Any) -> tuple[bytes, str, int | None]:
    url = str(getattr(attach, "url", "") or "").strip()
    if not url:
        raise ValueError("max audio attachment has no url")
    response = requests.get(
        url,
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0 (compatible; MessagerShop/1.0)"},
    )
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    extension = ".ogg"
    if "webm" in content_type:
        extension = ".webm"
    elif "mpeg" in content_type or "mp3" in content_type:
        extension = ".mp3"
    return response.content, extension, audio_duration_ms(attach)


def _voice_filename(extension: str) -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    normalized = ext.lower()
    if normalized not in {".ogg", ".opus", ".webm", ".mp3", ".m4a", ".wav"}:
        normalized = ".ogg"
    return f"voice{normalized}"


def _duration_ms(data: bytes, extension: str, duration_ms: int | None) -> int:
    if isinstance(duration_ms, int) and duration_ms > 0:
        return duration_ms
    try:
        with io.BytesIO(data) as bio:
            info = sf.info(bio)
        if info.duration and info.duration > 0:
            return max(1, int(round(info.duration * 1000)))
    except Exception:
        logger.debug("failed to read max voice duration via soundfile ext=%s", extension, exc_info=True)
    return 1000


def _build_voice_waveform(data: bytes) -> str:
    try:
        with io.BytesIO(data) as bio:
            samples, _samplerate = sf.read(bio, always_2d=False)
    except Exception:
        logger.debug("failed to build max voice waveform", exc_info=True)
        samples = None

    amps: list[float] = []
    if samples is not None and len(samples) > 0:
        if getattr(samples, "ndim", 1) > 1:
            mono = samples.mean(axis=1)
        else:
            mono = samples
        chunk = max(len(mono) // _WAVE_BARS, 1)
        for index in range(_WAVE_BARS):
            segment = mono[index * chunk : (index + 1) * chunk]
            if len(segment) == 0:
                amps.append(0.0)
                continue
            amps.append(float(abs(segment).max()))
    else:
        amps = [0.2] * _WAVE_BARS

    peak = max(amps) or 1.0
    normalized = [max(0.12, value / peak) for value in amps]

    image = Image.new("RGBA", (_WAVE_WIDTH, _WAVE_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    bar_width = max(_WAVE_WIDTH // _WAVE_BARS, 1)
    for index, amplitude in enumerate(normalized):
        bar_height = max(2, int(amplitude * (_WAVE_HEIGHT - 4)))
        x0 = index * bar_width + 1
        x1 = x0 + max(bar_width - 2, 1)
        y0 = (_WAVE_HEIGHT - bar_height) // 2
        y1 = y0 + bar_height
        draw.rounded_rectangle([x0, y0, x1, y1], radius=1, fill=(79, 140, 255, 255))

    buffer = io.BytesIO()
    image.save(buffer, format="WEBP")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def _next_message_cid() -> int:
    return int(time.time() * 1000)


async def _wait_upload_signal(
    app: Any,
    *,
    upload_kind: str,
    upload_id: int,
    timeout: float = 60.0,
) -> None:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    uploads = app.api.uploads
    waiters = uploads.video_upload_waiters if upload_kind == "video" else uploads.file_upload_waiters
    waiters[upload_id] = future
    try:
        await asyncio.wait_for(future, timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"timed out waiting for max voice upload kind={upload_kind} id={upload_id}"
        ) from exc
    finally:
        waiters.pop(upload_id, None)


async def _post_upload_bytes(
    app: Any,
    *,
    upload_url: str,
    filename: str,
    data: bytes,
) -> None:
    from pymax.exceptions import UploadError

    headers = {
        "Content-Disposition": f"attachment; filename={quote(filename)}",
        "Content-Length": str(len(data)),
        "Content-Range": f"0-{len(data) - 1}/{len(data)}",
        "Connection": "keep-alive",
    }
    async with (
        aiohttp.ClientSession(proxy=app.config.proxy) as session,
        session.post(
            url=upload_url,
            headers=headers,
            data=data,
        ) as http_response,
    ):
        if http_response.status != HTTPStatus.OK:
            raise UploadError(
                f"max voice upload failed with status {http_response.status} url={upload_url}"
            )


async def _upload_max_voice_via_file(
    client: Any,
    *,
    data: bytes,
    filename: str,
) -> tuple[str, int]:
    from pymax.api.uploads.models import FileUploadResponse
    from pymax.exceptions import UploadError
    from pymax.protocol import Opcode

    app = client._app
    extension = Path(filename).suffix.lstrip(".") or "ogg"
    response = await app.invoke(
        Opcode.FILE_UPLOAD,
        {
            "count": 1,
            "name": filename,
            "size": len(data),
            "ext": extension,
        },
    )
    try:
        upload_response = FileUploadResponse.model_validate(response.payload)
        upload_info = upload_response.info[0]
    except (ValidationError, IndexError, TypeError) as exc:
        raise UploadError("invalid max voice file upload response") from exc

    upload_url = str(upload_info.url or "").strip()
    token = str(upload_info.token or "").strip()
    file_id = int(upload_info.file_id or 0)
    if not upload_url or not token or not file_id:
        raise UploadError("max voice file upload response is missing url, token, or file_id")

    await _post_upload_bytes(app, upload_url=upload_url, filename=filename, data=data)
    await _wait_upload_signal(app, upload_kind="file", upload_id=file_id)
    return token, file_id


async def _upload_max_voice(
    client: Any,
    *,
    chat_id: int,
    data: bytes,
    filename: str,
) -> tuple[str, int, str]:
    from pymax.exceptions import UploadError

    # Voice notes are OGG/Opus files; FILE_UPLOAD is the correct pipeline for them.
    # VIDEO_UPLOAD expects real video and keeps returning attachment.not.ready for audio.
    _ = chat_id
    try:
        token, file_id = await _upload_max_voice_via_file(client, data=data, filename=filename)
        return token, file_id, "file"
    except (UploadError, TimeoutError, ConnectionError, ValidationError) as exc:
        max_trace("voice upload failed chat=%s kind=file err=%s", chat_id, exc)
        logger.debug("max voice upload via file failed", exc_info=True)
        raise UploadError("max voice upload failed") from exc


def _voice_send_attach_variants(
    *,
    token: str,
    media_id: int,
    duration_ms: int,
    wave: str,
    filename: str,
    file_size: int,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    duration_seconds = max(1, int(round(duration_ms / 1000)))
    return (
        ("AUDIO_TOKEN", {"_type": "AUDIO", "token": token}),
        (
            "AUDIO_ID",
            {
                "_type": "AUDIO",
                "token": token,
                "audioId": media_id,
                "duration": duration_seconds,
            },
        ),
        (
            "AUDIO_FULL",
            {
                "_type": "AUDIO",
                "token": token,
                "audioId": media_id,
                "duration": duration_seconds,
                "wave": wave,
            },
        ),
        (
            "FILE",
            {
                "_type": "FILE",
                "fileId": media_id,
                "token": token,
                "name": filename,
                "size": file_size,
            },
        ),
    )


async def _send_max_audio_message(
    client: Any,
    chat_id: int,
    *,
    token: str,
    audio_id: int,
    duration_ms: int,
    wave: str,
    upload_kind: str,
    filename: str,
    file_size: int,
    attempts: int = 20,
    retry_delay: float = 1.0,
) -> Any:
    from pymax.api.binding import bind_api_model
    from pymax.api.response import require_payload_model
    from pymax.exceptions import ApiError
    from pymax.protocol import Opcode
    from pymax.types.domain import Message

    app = client._app
    attach_variants = _voice_send_attach_variants(
        token=token,
        media_id=audio_id,
        duration_ms=duration_ms,
        wave=wave,
        filename=filename,
        file_size=file_size,
    )

    last_error: Exception | None = None
    for attach_type, attach in attach_variants:
        payload = {
            "chatId": chat_id,
            "message": {
                "text": "",
                "cid": _next_message_cid(),
                "elements": [],
                "attaches": [attach],
            },
            "notify": True,
        }
        for attempt in range(attempts):
            try:
                response = await app.invoke(Opcode.MSG_SEND, payload)
                message = bind_api_model(
                    app,
                    require_payload_model(response, Message),
                )
                max_trace(
                    "voice sent chat=%s media_id=%s upload=%s attach=%s attempt=%s",
                    chat_id,
                    audio_id,
                    upload_kind,
                    attach_type,
                    attempt + 1,
                )
                return message
            except ApiError as exc:
                last_error = exc
                error_key = str(exc.error or "")
                max_trace(
                    "voice send api error chat=%s media_id=%s upload=%s attach=%s attempt=%s error=%s detail=%s",
                    chat_id,
                    audio_id,
                    upload_kind,
                    attach_type,
                    attempt + 1,
                    error_key or exc,
                    exc,
                )
                if error_key == "attachment.not.ready" and attempt < attempts - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                break
            except ConnectionError as exc:
                last_error = exc
                max_trace(
                    "voice send connection error chat=%s media_id=%s upload=%s attach=%s attempt=%s err=%s",
                    chat_id,
                    audio_id,
                    upload_kind,
                    attach_type,
                    attempt + 1,
                    exc,
                )
                break

    if last_error is not None:
        raise last_error
    raise RuntimeError("max voice message send failed")


async def send_max_voice(
    client: Any,
    chat_id: int,
    *,
    data: bytes,
    extension: str,
    duration_ms: int | None = None,
) -> Any:
    filename = _voice_filename(extension)
    resolved_duration_ms = _duration_ms(data, extension, duration_ms)
    wave = _build_voice_waveform(data)

    max_trace(
        "voice upload start chat=%s bytes=%s ext=%s duration_ms=%s",
        chat_id,
        len(data),
        extension,
        resolved_duration_ms,
    )
    token, audio_id, upload_kind = await _upload_max_voice(
        client,
        chat_id=chat_id,
        data=data,
        filename=filename,
    )
    max_trace(
        "voice upload done chat=%s audio_id=%s token_len=%s upload=%s",
        chat_id,
        audio_id,
        len(token),
        upload_kind,
    )
    await asyncio.sleep(1.0)
    return await _send_max_audio_message(
        client,
        chat_id,
        token=token,
        audio_id=audio_id,
        duration_ms=resolved_duration_ms,
        wave=wave,
        upload_kind=upload_kind,
        filename=filename,
        file_size=len(data),
    )


def voice_message_fields(duration_ms: int | None = None) -> dict[str, Any]:
    return {
        "text": VOICE_MESSAGE_TEXT,
        "message_type": MESSAGE_TYPE_VOICE,
        "duration_ms": duration_ms,
    }
