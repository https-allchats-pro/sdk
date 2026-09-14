"""Optional metrics hooks. Backend can replace recorders at startup."""

from __future__ import annotations

from typing import Any, Callable

__all__ = [
    "configure_metrics",
    "record_auth",
    "record_message",
]


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


record_auth: Callable[..., Any] = _noop
record_message: Callable[..., Any] = _noop


def configure_metrics(
    *,
    auth: Callable[..., Any] | None = None,
    message: Callable[..., Any] | None = None,
) -> None:
    global record_auth, record_message
    if auth is not None:
        record_auth = auth
    if message is not None:
        record_message = message
