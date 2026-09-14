"""Public package-root API surface."""

from __future__ import annotations

import unittest

import allchats_sdk
from allchats_sdk import (
    Account,
    AllChatsError,
    Capability,
    Chat,
    ConnectionState,
    ConnectionStatus,
    CredentialStore,
    FileCredentialStore,
    MAXClient,
    MAXProvider,
    MaxMessengerClient,
    MemoryCredentialStore,
    Message,
    MessengerClient,
    TelegramClient,
    TelegramProvider,
    VKClient,
    VKProvider,
)


class PublicApiTests(unittest.TestCase):
    def test_root_exports_match_all(self) -> None:
        exported = set(allchats_sdk.__all__)
        self.assertEqual(
            exported,
            {
                "Account",
                "AllChatsError",
                "Capability",
                "Chat",
                "ConnectionState",
                "ConnectionStatus",
                "CredentialStore",
                "FileCredentialStore",
                "MAXClient",
                "MAXProvider",
                "MaxMessengerClient",
                "MemoryCredentialStore",
                "Message",
                "MessengerClient",
                "TelegramClient",
                "TelegramProvider",
                "VKClient",
                "VKProvider",
                "__version__",
            },
        )

    def test_public_symbols_are_importable(self) -> None:
        self.assertTrue(issubclass(AllChatsError, Exception))
        self.assertEqual(Capability.MESSAGES.value, "messages")
        self.assertEqual(Message(id="1", chat_id="c").id, "1")
        self.assertEqual(Chat(id="c").id, "c")
        self.assertEqual(Account(id="a", provider="telegram").provider, "telegram")
        self.assertEqual(ConnectionState(connection_id="a", state=ConnectionStatus.AUTHORIZED).state, ConnectionState.AUTHORIZED)
        self.assertIs(ConnectionState.PASSWORD_REQUIRED, ConnectionStatus.PASSWORD_REQUIRED)
        self.assertEqual(TelegramProvider.provider_id, "telegram")
        self.assertEqual(VKProvider.provider_id, "vk")
        self.assertEqual(MAXProvider.provider_id, "max")
        self.assertEqual(TelegramClient.provider_id, "telegram")
        self.assertEqual(VKClient.provider_id, "vk")
        self.assertEqual(MAXClient.provider_id, "max")
        self.assertIs(MessengerClient, allchats_sdk.MessengerClient)
        self.assertIs(MaxMessengerClient, allchats_sdk.MaxMessengerClient)

    def test_messenger_error_alias_still_works(self) -> None:
        from allchats_sdk.errors import MessengerError, ValidationError

        self.assertIs(MessengerError, AllChatsError)
        self.assertTrue(issubclass(ValidationError, AllChatsError))

    def test_telegram_account_client_wiring(self) -> None:
        try:
            store = MemoryCredentialStore()
            client = TelegramClient(
                "acc-1",
                app_id=1,
                app_hash="hash",
                credential_store=store,
            )
        except ModuleNotFoundError as exc:
            self.skipTest(f"telegram extras unavailable: {exc}")
        self.assertEqual(client.account_id, "acc-1")
        self.assertEqual(client.provider_id, "telegram")
        self.assertIsInstance(client.provider, TelegramProvider)
        self.assertIs(client.credential_store, store)

    def test_max_account_client_wiring(self) -> None:
        host = object()
        client = MAXClient(account_id="acc-max", session_host=host)
        self.assertEqual(client.provider_id, "max")
        self.assertIsInstance(client.provider, MAXProvider)

    def test_provider_submodule_imports(self) -> None:
        from allchats_sdk.telegram import TelegramClient as Tg
        from allchats_sdk.vk import VKClient as Vk
        from allchats_sdk.max import MAXClient as Mx

        self.assertIs(Tg, TelegramClient)
        self.assertIs(Vk, VKClient)
        self.assertIs(Mx, MAXClient)


if __name__ == "__main__":
    unittest.main()
