"""ffmpeg-backed audio conversion helpers (Telegram voice, etc.)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

TELEGRAM_VOICE_EXTENSIONS = {".ogg", ".opus"}
MIN_AUDIO_BYTES = 512


class AudioConversionError(ValueError):
    pass


def _convert_to_ogg_opus_sync(data: bytes, input_suffix: str) -> bytes:
    if len(data) < MIN_AUDIO_BYTES:
        raise AudioConversionError("voice recording is too short or empty")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not installed")

    suffix = input_suffix if input_suffix.startswith(".") else f".{input_suffix}"
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / f"input{suffix}"
        output_path = Path(tmpdir) / "output.ogg"
        input_path.write_bytes(data)

        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-ac",
                "1",
                "-ar",
                "48000",
                "-c:a",
                "libopus",
                "-b:a",
                "48k",
                "-application",
                "voip",
                "-avoid_negative_ts",
                "make_zero",
                str(output_path),
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            logger.warning(
                "ffmpeg conversion failed input_bytes=%s suffix=%s stderr=%s",
                len(data),
                suffix,
                result.stderr.decode("utf-8", errors="replace")[-500:],
            )
            raise AudioConversionError("failed to convert voice message to ogg/opus format")
        return output_path.read_bytes()


async def prepare_telegram_voice_bytes(data: bytes, extension: str) -> tuple[bytes, str]:
    return await prepare_ogg_voice_bytes(data, extension)


WHISPER_SAMPLE_RATE = 16000


def _convert_to_whisper_wav_sync(data: bytes, input_suffix: str) -> bytes:
    if len(data) < MIN_AUDIO_BYTES:
        raise AudioConversionError("voice recording is too short or empty")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is not installed")

    suffix = input_suffix if input_suffix.startswith(".") else f".{input_suffix}"
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / f"input{suffix}"
        output_path = Path(tmpdir) / "output.wav"
        input_path.write_bytes(data)

        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(input_path),
                "-ac",
                "1",
                "-ar",
                str(WHISPER_SAMPLE_RATE),
                str(output_path),
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
            logger.warning(
                "ffmpeg whisper wav conversion failed input_bytes=%s suffix=%s stderr=%s",
                len(data),
                suffix,
                result.stderr.decode("utf-8", errors="replace")[-500:],
            )
            raise AudioConversionError("failed to convert voice message to whisper wav format")
        return output_path.read_bytes()


async def convert_to_whisper_wav(data: bytes, extension: str) -> bytes:
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    return await asyncio.to_thread(_convert_to_whisper_wav_sync, data, ext)


async def prepare_ogg_voice_bytes(data: bytes, extension: str) -> tuple[bytes, str]:
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext in TELEGRAM_VOICE_EXTENSIONS:
        return data, ".ogg"

    try:
        converted = await asyncio.to_thread(_convert_to_ogg_opus_sync, data, ext)
        return converted, ".ogg"
    except AudioConversionError:
        raise
    except Exception:
        logger.exception("failed to convert audio to ogg/opus for telegram")
        raise
