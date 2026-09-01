"""Error helper tests."""

from __future__ import annotations

import unittest

from allchats_sdk.errors import (
    MessengerClientUnavailableError,
    MessengerError,
    SessionNotConnectedError,
    UnsupportedCapabilityError,
    ValidationError,
    is_telegram_rpc_error,
)


class ErrorTests(unittest.TestCase):
    def test_exception_hierarchy(self) -> None:
        self.assertTrue(issubclass(ValidationError, MessengerError))
        self.assertTrue(issubclass(MessengerClientUnavailableError, MessengerError))
        self.assertTrue(issubclass(UnsupportedCapabilityError, MessengerError))

    def test_session_not_connected_carries_status(self) -> None:
        exc = SessionNotConnectedError("waiting_qr")
        self.assertEqual(exc.status, "waiting_qr")
        self.assertIn("waiting_qr", str(exc))

    def test_unsupported_capability_fields(self) -> None:
        exc = UnsupportedCapabilityError("telegram", "messages.send")
        self.assertEqual(exc.provider, "telegram")
        self.assertEqual(exc.capability, "messages.send")

    def test_is_telegram_rpc_error_without_telethon(self) -> None:
        self.assertFalse(is_telegram_rpc_error(ValueError("nope")))


if __name__ == "__main__":
    unittest.main()
