"""Deprecated compatibility shim.

Use ``allchats_sdk.providers.vk.provider`` (``VKProvider``).
"""

from __future__ import annotations

from allchats_sdk.providers.vk.provider import (
    VKProvider,
    VkAccountClient,
    VkClientManager,
)

__all__ = [
    "VKProvider",
    "VkAccountClient",
    "VkClientManager",
]
