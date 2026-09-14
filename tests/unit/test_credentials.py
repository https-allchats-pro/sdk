"""Credentials helpers tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from allchats_sdk.credentials import (
    avito_authorized,
    discord_authorized,
    ensure_native_max_credentials,
    is_authorized,
    merge_credentials,
    new_telegram_credentials,
    new_vk_credentials,
    new_whatsapp_credentials,
    parse_client_session_id,
    sanitize_credentials,
    telegram_authorized,
    vk_authorized,
    whatsapp_authorized,
)


class CredentialsTests(unittest.TestCase):
    def test_parse_client_session_id(self) -> None:
        self.assertEqual(parse_client_session_id(None), 0)
        self.assertEqual(parse_client_session_id(""), 0)
        self.assertEqual(parse_client_session_id(42), 42)
        self.assertEqual(parse_client_session_id("7"), 7)

    def test_telegram_authorized_by_user_id_or_session(self) -> None:
        self.assertTrue(telegram_authorized({"user_id": "123", "session_data": ""}))
        self.assertTrue(telegram_authorized({"user_id": "", "session_data": "abc"}))
        self.assertFalse(telegram_authorized({"user_id": "", "session_data": ""}))

    def test_provider_authorized_helpers(self) -> None:
        self.assertTrue(vk_authorized({"user_id": "1", "access_token": "tok"}))
        self.assertFalse(vk_authorized({"user_id": "1", "access_token": ""}))

        self.assertTrue(whatsapp_authorized({"state_instance": "authorized"}))
        self.assertFalse(whatsapp_authorized({"state_instance": "notAuthorized"}))

        self.assertTrue(discord_authorized({"user_id": "1", "token": "tok"}))
        self.assertTrue(avito_authorized({"user_id": "1", "access_token": "tok"}))

    def test_is_authorized_by_messenger_type(self) -> None:
        self.assertTrue(is_authorized({"protocol": "native", "auth_token": ""}, "native"))
        self.assertTrue(is_authorized({"session_data": "x"}, "telegram"))
        self.assertTrue(is_authorized({"user_id": "1", "access_token": "t"}, "vk"))
        self.assertFalse(is_authorized({}, "vk"))

    def test_sanitize_credentials_masks_sensitive_values(self) -> None:
        sanitized = sanitize_credentials(
            {
                "user_id": "42",
                "access_token": "secret-token",
                "session_data": "session",
                "proxy": {"host": "127.0.0.1", "password": "proxy-pass"},
            }
        )
        self.assertEqual(sanitized["user_id"], "42")
        self.assertEqual(sanitized["access_token"], "***")
        self.assertEqual(sanitized["session_data"], "***")
        self.assertEqual(sanitized["proxy"]["password"], "***")
        self.assertEqual(sanitized["proxy"]["host"], "127.0.0.1")

    def test_merge_credentials_coerces_client_session_id(self) -> None:
        merged = merge_credentials({"client_session_id": "3"}, {"user_id": "1"})
        self.assertEqual(merged["client_session_id"], 3)
        self.assertEqual(merged["user_id"], "1")

    def test_new_credentials_factories(self) -> None:
        telegram = new_telegram_credentials(account_id="acc-1")
        self.assertEqual(telegram["device_id"], "acc-1")
        self.assertEqual(telegram["session_data"], "")

        vk = new_vk_credentials(account_id="acc-2", proxy={"host": "127.0.0.1"})
        self.assertEqual(vk["device_id"], "acc-2")
        self.assertEqual(vk["proxy"]["host"], "127.0.0.1")

        whatsapp = new_whatsapp_credentials(account_id="acc-3")
        self.assertEqual(whatsapp["protocol"], "web")

    def test_ensure_native_max_credentials(self) -> None:
        result = ensure_native_max_credentials(
            {"auth_token": "tok"},
            account_id="acc-max",
            proxy={"host": "127.0.0.1"},
        )
        self.assertEqual(result["protocol"], "native")
        self.assertEqual(result["device_id"], "acc-max")
        self.assertEqual(result["auth_token"], "tok")
        self.assertGreater(result["client_session_id"], 0)
        self.assertTrue(str(result["mt_instance_id"]).strip())

    def test_avito_sync_started_at_ms(self) -> None:
        from allchats_sdk.credentials import avito_sync_started_at_ms

        self.assertEqual(avito_sync_started_at_ms({"sync_started_at": 12345}), 12345)
        fallback = datetime(2024, 1, 1, tzinfo=UTC)
        self.assertEqual(
            avito_sync_started_at_ms({}, fallback=fallback),
            int(fallback.timestamp() * 1000),
        )


if __name__ == "__main__":
    unittest.main()
