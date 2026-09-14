"""Deprecated compatibility shim.

Use ``allchats_sdk.internal.hooks`` instead.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "SpeechRecognitionError",
    "set_transcriber",
    "transcribe_voice_bytes",
]


def __getattr__(name: str) -> Any:
    from allchats_sdk.internal import hooks as _hooks

    return getattr(_hooks, name)
