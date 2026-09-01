"""Optional speech recognition hook (injected by host application)."""

from __future__ import annotations

from typing import Any, Callable, Awaitable

TranscribeFn = Callable[..., Awaitable[Any]]

_transcribe: TranscribeFn | None = None


class SpeechRecognitionError(Exception):
    pass


def set_transcriber(fn: TranscribeFn | None) -> None:
    global _transcribe
    _transcribe = fn


async def transcribe_voice_bytes(*args: Any, **kwargs: Any) -> Any:
    if _transcribe is None:
        raise SpeechRecognitionError("speech recognition is not configured")
    return await _transcribe(*args, **kwargs)
