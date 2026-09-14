"""Register built-in providers on the default registry."""

from __future__ import annotations

from allchats_sdk.internal.registry import ProviderRegistry, default_registry

__all__ = ["register_builtin_providers"]


def register_builtin_providers(registry: ProviderRegistry | None = None) -> ProviderRegistry:
    target = registry or default_registry

    def _telegram(**kwargs):
        from allchats_sdk.providers.telegram.provider import TelegramProvider

        return TelegramProvider(**kwargs)

    def _vk(**kwargs):
        from allchats_sdk.providers.vk.provider import VKProvider

        return VKProvider(**kwargs)

    def _avito(**kwargs):
        from allchats_sdk.providers.avito.manager import AvitoClientManager

        return AvitoClientManager(**kwargs)

    def _whatsapp(**kwargs):
        from allchats_sdk.providers.whatsapp.manager import WhatsAppClientManager

        return WhatsAppClientManager(**kwargs)

    def _discord(**kwargs):
        from allchats_sdk.providers.discord.manager import DiscordClientManager

        return DiscordClientManager(**kwargs)

    target.register("telegram", _telegram)
    target.register("vk", _vk)
    target.register("avito", _avito)
    target.register("whatsapp", _whatsapp)
    target.register("discord", _discord)
    # Max is wired through SessionManager + MaxRuntimeFactory (host-owned session model).
    return target
