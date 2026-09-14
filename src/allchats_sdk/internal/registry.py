"""Provider factory registry (SDK-internal).

Prefer typed providers / account clients for application code::

    from allchats_sdk import TelegramClient, TelegramProvider
"""

from __future__ import annotations

from typing import Any, Callable

from allchats_sdk.protocols import MessengerProvider

__all__ = [
    "ProviderFactory",
    "ProviderRegistry",
    "default_registry",
]

ProviderFactory = Callable[..., MessengerProvider]


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, provider_id: str, factory: ProviderFactory) -> None:
        key = provider_id.strip().lower()
        if not key:
            raise ValueError("provider_id is required")
        self._factories[key] = factory

    def create(self, provider_id: str, **kwargs: Any) -> MessengerProvider:
        key = provider_id.strip().lower()
        factory = self._factories.get(key)
        if factory is None:
            known = ", ".join(sorted(self._factories)) or "(none)"
            raise KeyError(f"unknown messenger provider '{provider_id}'; known: {known}")
        return factory(**kwargs)

    def available(self) -> list[str]:
        return sorted(self._factories)

    def __contains__(self, provider_id: object) -> bool:
        return str(provider_id or "").strip().lower() in self._factories


default_registry = ProviderRegistry()
