"""Deprecated compatibility shim.

Use ``allchats_sdk.internal.registry`` instead.
"""

from __future__ import annotations

from allchats_sdk.internal.registry import ProviderFactory, ProviderRegistry, default_registry

__all__ = [
    "ProviderFactory",
    "ProviderRegistry",
    "default_registry",
]
