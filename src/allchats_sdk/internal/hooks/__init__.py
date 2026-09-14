"""Optional host-injected hooks (speech recognition, …)."""

from __future__ import annotations

from allchats_sdk.internal.hooks.speech import (
    SpeechRecognitionError,
    set_transcriber,
    transcribe_voice_bytes,
)

__all__ = [
    "SpeechRecognitionError",
    "set_transcriber",
    "transcribe_voice_bytes",
]
