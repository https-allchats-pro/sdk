"""Integration-style checks for installed package import paths.

These assert the public entrypoints consumers use after ``pip install``.
"""

from __future__ import annotations

import importlib
import unittest


class PackageImportTests(unittest.TestCase):
    def test_root_package_exports_clients(self) -> None:
        import allchats_sdk

        for name in ("TelegramClient", "VKClient", "MAXClient", "FileCredentialStore"):
            self.assertIn(name, allchats_sdk.__all__)
            self.assertTrue(hasattr(allchats_sdk, name))

    def test_provider_submodules_importable(self) -> None:
        for module_name, attr in (
            ("allchats_sdk.telegram", "TelegramClient"),
            ("allchats_sdk.vk", "VKClient"),
            ("allchats_sdk.max", "MAXClient"),
        ):
            module = importlib.import_module(module_name)
            self.assertTrue(hasattr(module, attr), module_name)

    def test_telegram_client_from_submodule(self) -> None:
        from allchats_sdk.telegram import TelegramClient

        self.assertEqual(TelegramClient.provider_id, "telegram")

    def test_credential_store_from_root(self) -> None:
        from allchats_sdk import FileCredentialStore, MemoryCredentialStore

        store = MemoryCredentialStore()
        self.assertTrue(callable(FileCredentialStore))
        self.assertIsNotNone(store)


if __name__ == "__main__":
    unittest.main()
