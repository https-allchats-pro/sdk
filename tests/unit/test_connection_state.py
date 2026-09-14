"""Connection state / wait_until_authorized tests."""

from __future__ import annotations

import unittest
from typing import Any

from allchats_sdk.client import MessengerClient
from allchats_sdk.errors import AllChatsError
from allchats_sdk.models import ConnectionState, ConnectionStatus


class _AuthStateProvider:
    provider_id = "mock"

    def __init__(self) -> None:
        self.states = ["starting", "passwordRequired", "authorized"]
        self.passwords: list[str] = []
        self._idx = 0
        self.user_id = ""

    def client_for_account(self, account_id: str) -> Any:
        _ = account_id
        state = self.states[min(self._idx, len(self.states) - 1)]
        self._idx += 1
        return type(
            "S",
            (),
            {
                "state_instance": state,
                "user_id": "42" if state == "authorized" else "",
                "error": "",
            },
        )()

    async def submit_password(self, account_id: str, password: str) -> None:
        _ = account_id
        self.passwords.append(password)

    async def connect_account(self, account_id: str, credentials: dict[str, Any]) -> dict[str, Any]:
        return {"account_id": account_id, "credentials": credentials}


class ConnectionStateTests(unittest.TestCase):
    def test_typed_constants(self) -> None:
        self.assertIs(ConnectionState.AUTHORIZED, ConnectionStatus.AUTHORIZED)
        self.assertIs(ConnectionState.PASSWORD_REQUIRED, ConnectionStatus.PASSWORD_REQUIRED)

    def test_from_raw_maps_provider_state(self) -> None:
        raw = type("S", (), {"state_instance": "passwordRequired", "user_id": "", "error": ""})()
        status = ConnectionState.from_raw("acc-1", raw)
        self.assertEqual(status.state, ConnectionState.PASSWORD_REQUIRED)
        self.assertTrue(status.is_password_required)


class WaitUntilAuthorizedTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_until_authorized_handles_password(self) -> None:
        provider = _AuthStateProvider()
        client = MessengerClient(provider=provider, account_id="acc-1")
        assert client.auth is not None
        status = await client.auth.wait_until_authorized(
            password_provider=lambda: "secret",
            poll_interval_sec=0.01,
        )
        self.assertTrue(status.is_authorized)
        self.assertEqual(status.user_id, "42")
        self.assertEqual(provider.passwords, ["secret"])

    async def test_wait_until_authorized_requires_password_provider(self) -> None:
        provider = _AuthStateProvider()
        provider.states = ["passwordRequired"]
        client = MessengerClient(provider=provider, account_id="acc-1")
        assert client.auth is not None
        with self.assertRaises(AllChatsError):
            await client.auth.wait_until_authorized(poll_interval_sec=0.01, timeout_sec=0.05)


if __name__ == "__main__":
    unittest.main()
