"""Deprecated compatibility shim.

Use ``allchats_sdk.internal.runtime.register`` instead.
"""

from __future__ import annotations

from allchats_sdk.internal.runtime.register import register_builtin_providers

__all__ = ["register_builtin_providers"]
