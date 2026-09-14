"""Deprecated compatibility shim.

Use ``allchats_sdk.providers.max.auth`` instead.
"""

from __future__ import annotations

from allchats_sdk.providers.max.auth import (
    WebPasswordProvider,
    WebQrHandler,
    WebSmsCodeProvider,
)

__all__ = [
    "WebPasswordProvider",
    "WebQrHandler",
    "WebSmsCodeProvider",
]
