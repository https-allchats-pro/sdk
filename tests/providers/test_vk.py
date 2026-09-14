"""Public VK client surface (preferred import path)."""

from __future__ import annotations

import unittest


class VKPublicApiTests(unittest.TestCase):
    def test_submodule_import(self) -> None:
        from allchats_sdk.vk import VKClient, VKProvider

        self.assertEqual(VKClient.provider_id, "vk")
        self.assertEqual(VKProvider.provider_id, "vk")

    def test_root_and_submodule_same_client(self) -> None:
        import allchats_sdk
        from allchats_sdk.vk import VKClient as SubClient

        self.assertIs(allchats_sdk.VKClient, SubClient)

    def test_client_constructs_with_memory_store(self) -> None:
        from allchats_sdk import MemoryCredentialStore
        from allchats_sdk.vk import VKClient

        try:
            client = VKClient(
                "acc-vk",
                credential_store=MemoryCredentialStore(),
            )
        except ModuleNotFoundError as exc:
            self.skipTest(f"vk extras unavailable: {exc}")
        self.assertEqual(client.account_id, "acc-vk")
        self.assertEqual(client.provider_id, "vk")
        self.assertIsNotNone(client.auth)


if __name__ == "__main__":
    unittest.main()
