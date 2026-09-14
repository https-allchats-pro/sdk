"""Public MAX client surface (preferred import path)."""

from __future__ import annotations

import unittest


class MAXPublicApiTests(unittest.TestCase):
    def test_submodule_import(self) -> None:
        from allchats_sdk.max import MAXClient, MAXProvider

        self.assertEqual(MAXClient.provider_id, "max")
        self.assertEqual(MAXProvider.provider_id, "max")

    def test_root_and_submodule_same_client(self) -> None:
        import allchats_sdk
        from allchats_sdk.max import MAXClient as SubClient

        self.assertIs(allchats_sdk.MAXClient, SubClient)

    def test_client_constructs_with_session_host(self) -> None:
        from allchats_sdk.max import MAXClient

        host = object()
        client = MAXClient(account_id="acc-max", session_host=host)
        self.assertEqual(client.account_id, "acc-max")
        self.assertEqual(client.provider_id, "max")
        self.assertIs(client.provider.session_host, host)
        self.assertIsNotNone(client.auth)
        self.assertIsNotNone(client.messages)


if __name__ == "__main__":
    unittest.main()
