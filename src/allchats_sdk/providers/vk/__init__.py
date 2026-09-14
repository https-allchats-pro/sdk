"""VK messenger provider package."""

from __future__ import annotations

from typing import Any

__all__ = [
    "VKProvider",
    "VkAccountClient",
    "VkClientManager",
]


def __getattr__(name: str) -> Any:
    if name in {"VKProvider", "VkAccountClient", "VkClientManager"}:
        from allchats_sdk.providers.vk.provider import (
            VKProvider,
            VkAccountClient,
            VkClientManager,
        )

        return {
            "VKProvider": VKProvider,
            "VkAccountClient": VkAccountClient,
            "VkClientManager": VkClientManager,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
