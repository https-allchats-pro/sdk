"""MessengerClient facade tests."""

from __future__ import annotations

import unittest
from typing import Any

from allchats_sdk.client import MaxMessengerClient, MessengerClient
from allchats_sdk.errors import MessengerClientUnavailableError, UnsupportedCapabilityError
from allchats_sdk.registry import ProviderRegistry


class _MockCredentials:
    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self._data = data

    async def get(self, account_id: str) -> dict[str, Any] | None:
        return self._data.get(account_id)


class _MockProvider:
    provider_id = "telegram"

    def __init__(self) -> None:
        self.connected_with: dict[str, Any] | None = None
        self.sent: list[dict[str, Any]] = []
        self.disconnected: list[str] = []

    async def connect_account(self, account_id: str, credentials: dict[str, Any]) -> dict[str, Any]:
        self.connected_with = {"account_id": account_id, "credentials": credentials}
        return self.connected_with

    async def send_message(
        self,
        account_id: str,
        *,
        text: str,
        chat_id: str | None = None,
        phone_number: str | None = None,
        reply_to_external_id: str | None = None,
    ) -> tuple[str, str]:
        payload = {
            "account_id": account_id,
            "text": text,
            "chat_id": chat_id,
            "phone_number": phone_number,
            "reply_to_external_id": reply_to_external_id,
        }
        self.sent.append(payload)
        return ("msg-1", chat_id or phone_number or "")

    def client_for_account(self, account_id: str) -> dict[str, str]:
        return {"account_id": account_id, "state": "authorized"}

    async def start_qr(self, account_id: str, credentials: dict[str, Any], *, refresh: bool = False) -> dict[str, str]:
        return {"account_id": account_id, "qr": "link", "refresh": str(refresh), "credentials": str(bool(credentials))}

    async def disconnect(self, account_id: str) -> None:
        self.disconnected.append(account_id)


class _MockRuntime:
    def __init__(self, session_id: str) -> None:
        self.snapshot = type("Snapshot", (), {"session_id": session_id})()


class _MockMaxHost:
    def __init__(self) -> None:
        self.runtime = _MockRuntime("sess-1")
        self.sent: list[dict[str, Any]] = []

    def find_account_runtime(self, account_id: str) -> _MockRuntime | None:
        if account_id == "acc-max":
            return self.runtime
        return None

    async def connect_account(self, account_id: str) -> dict[str, str]:
        return {"account_id": account_id, "connected": "true"}

    async def send_message(
        self,
        session_id: str,
        chat_id: int,
        text: str,
        *,
        reply_to: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "session_id": session_id,
            "chat_id": chat_id,
            "text": text,
            "reply_to": reply_to,
        }
        self.sent.append(payload)
        return payload

    async def start_qr_for_account(self, account_id: str, credentials: dict[str, Any]) -> dict[str, Any]:
        return {"account_id": account_id, "credentials": credentials}

    async def stop_account_sessions(self, account_id: str) -> None:
        self.stopped = account_id


class MessengerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_connect_uses_credential_storage(self) -> None:
        provider = _MockProvider()
        storage = _MockCredentials({"acc-1": {"token": "abc"}})
        client = MessengerClient.from_provider("telegram", "acc-1", provider, credential_storage=storage)
        result = await client.connect()
        self.assertEqual(result["credentials"], {"token": "abc"})
        self.assertEqual(provider.connected_with["account_id"], "acc-1")

    async def test_messages_send_delegates_to_provider(self) -> None:
        provider = _MockProvider()
        client = MessengerClient.from_provider("telegram", "acc-1", provider)
        message_id, chat_id = await client.messages.send("hello", chat_id="123")
        self.assertEqual(message_id, "msg-1")
        self.assertEqual(chat_id, "123")
        self.assertEqual(provider.sent[0]["text"], "hello")

    async def test_chats_client_state(self) -> None:
        provider = _MockProvider()
        client = MessengerClient.from_provider("telegram", "acc-1", provider)
        state = await client.chats.client_state()
        self.assertEqual(state["state"], "authorized")

    async def test_auth_start_qr(self) -> None:
        provider = _MockProvider()
        client = MessengerClient.from_provider("telegram", "acc-1", provider)
        auth = client.auth
        assert auth is not None
        result = await auth.start_qr({"session": "x"})
        self.assertEqual(result["qr"], "link")

    async def test_unsupported_messages_raises(self) -> None:
        registry = ProviderRegistry()
        registry.register("minimal", lambda **kwargs: object())
        client = MessengerClient("minimal", "acc-1", registry=registry)
        with self.assertRaises(UnsupportedCapabilityError):
            _ = client.messages

    async def test_from_provider_kw_preferred(self) -> None:
        provider = _MockProvider()
        client = MessengerClient(provider=provider, account_id="acc-1")
        self.assertEqual(client.provider_id, "telegram")
        await client.connect({"token": "1"})

    async def test_legacy_registry_factory_create(self) -> None:
        registry = ProviderRegistry()

        class _MockWithId(_MockProvider):
            provider_id = "mock"

        registry.register("mock", lambda **kwargs: _MockWithId())
        client = MessengerClient("mock", "acc-1", registry=registry)
        await client.connect({"token": "1"})
        message_id, _ = await client.messages.send("ping", chat_id="42")
        self.assertEqual(message_id, "msg-1")


class MaxMessengerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_message_via_session_host(self) -> None:
        host = _MockMaxHost()
        client = MaxMessengerClient("acc-max", session_host=host)
        result = await client.messages.send("hi", chat_id="777")
        self.assertEqual(result["chat_id"], 777)
        self.assertEqual(host.sent[0]["session_id"], "sess-1")

    async def test_send_without_runtime_raises(self) -> None:
        host = _MockMaxHost()
        client = MaxMessengerClient("missing", session_host=host)
        with self.assertRaises(MessengerClientUnavailableError):
            await client.messages.send("hi", chat_id="1")


if __name__ == "__main__":
    unittest.main()
