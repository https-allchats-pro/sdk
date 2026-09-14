"""Public Telegram client surface (preferred import path)."""

from __future__ import annotations

import unittest


class TelegramPublicApiTests(unittest.TestCase):
    def test_submodule_import(self) -> None:
        from allchats_sdk.telegram import TelegramClient, TelegramProvider

        self.assertEqual(TelegramClient.provider_id, "telegram")
        self.assertEqual(TelegramProvider.provider_id, "telegram")

    def test_root_and_submodule_same_client(self) -> None:
        import allchats_sdk
        from allchats_sdk.telegram import TelegramClient as SubClient

        self.assertIs(allchats_sdk.TelegramClient, SubClient)

    def test_client_constructs_with_memory_store(self) -> None:
        from allchats_sdk import MemoryCredentialStore
        from allchats_sdk.telegram import TelegramClient

        try:
            client = TelegramClient(
                "acc-1",
                app_id=1,
                app_hash="hash",
                credential_store=MemoryCredentialStore(),
            )
        except ModuleNotFoundError as exc:
            self.skipTest(f"telegram extras unavailable: {exc}")
        self.assertEqual(client.account_id, "acc-1")
        self.assertEqual(client.provider_id, "telegram")
        self.assertIsNotNone(client.auth)
        self.assertIsNotNone(client.messages)


if __name__ == "__main__":
    unittest.main()
