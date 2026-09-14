"""Provider package layout and conceptual API."""

from __future__ import annotations

import inspect
import unittest

from allchats_sdk.providers.max.provider import MAXProvider
from allchats_sdk.providers.telegram.provider import TelegramProvider
from allchats_sdk.providers.vk.provider import VKProvider


_CONCEPTUAL = (
    "connect_account",
    "start_qr",
    "disconnect",
    "send_message",
    "client_for_account",
)


class ProviderStructureTests(unittest.TestCase):
    def test_telegram_exports(self) -> None:
        from allchats_sdk.providers import telegram

        self.assertIs(telegram.TelegramProvider, TelegramProvider)
        self.assertTrue(hasattr(telegram, "TelegramAccountClient"))

    def test_vk_exports(self) -> None:
        from allchats_sdk.providers import vk

        self.assertIs(vk.VKProvider, VKProvider)

    def test_max_exports(self) -> None:
        from allchats_sdk.providers import max as max_provider

        self.assertIs(max_provider.MAXProvider, MAXProvider)

    def test_manager_shims(self) -> None:
        from allchats_sdk.providers.telegram import manager as tg_manager
        from allchats_sdk.providers.vk import manager as vk_manager

        self.assertIs(tg_manager.TelegramClientManager, TelegramProvider)
        self.assertIs(vk_manager.VkClientManager, VKProvider)

    def test_conceptual_api_methods_exist(self) -> None:
        for cls in (TelegramProvider, VKProvider, MAXProvider):
            for name in _CONCEPTUAL:
                self.assertTrue(hasattr(cls, name), f"{cls.__name__}.{name}")

    def test_start_qr_accepts_credentials(self) -> None:
        for cls in (TelegramProvider, VKProvider, MAXProvider):
            params = inspect.signature(cls.start_qr).parameters
            self.assertIn("credentials", params, cls.__name__)


if __name__ == "__main__":
    unittest.main()
