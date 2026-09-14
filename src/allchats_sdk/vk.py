"""Public VK entrypoints.

Preferred after install::

    from allchats_sdk.vk import VKClient
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "VKClient",
    "VKProvider",
]


def __getattr__(name: str) -> Any:
    if name == "VKClient":
        from allchats_sdk.clients.vk import VKClient

        return VKClient
    if name == "VKProvider":
        from allchats_sdk.providers.vk.provider import VKProvider

        return VKProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
