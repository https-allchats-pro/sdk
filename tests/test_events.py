"""Event payload tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from allchats_sdk.events import (
    ChatIdRemapEvent,
    ChatsDiscoveredEvent,
    ConnectionStateEvent,
    CredentialsUpdatedEvent,
    IncomingMessageEvent,
    OutgoingMessageEvent,
)


class EventPayloadTests(unittest.TestCase):
    def test_incoming_message_event_metadata_defaults(self) -> None:
        sent_at = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)
        event = IncomingMessageEvent(
            connection_id="acc-1",
            provider="telegram",
            external_chat_id="123",
            external_message_id="99",
            from_id="456",
            text="hello",
            sent_at=sent_at,
            metadata={
                "message_type": "voice",
                "media_path": "/tmp/voice.ogg",
                "duration_ms": 1500,
            },
        )
        self.assertEqual(event.provider, "telegram")
        self.assertEqual(event.metadata["message_type"], "voice")
        self.assertEqual(event.metadata["media_path"], "/tmp/voice.ogg")
        self.assertEqual(event.metadata["duration_ms"], 1500)
        self.assertFalse(event.is_group)

    def test_outgoing_message_event_fields(self) -> None:
        event = OutgoingMessageEvent(
            connection_id="acc-1",
            provider="vk",
            external_chat_id="200",
            external_message_id="10",
            text="reply",
            from_id="acc-1",
            metadata={"emit_ws": False},
        )
        self.assertEqual(event.from_id, "acc-1")
        self.assertFalse(event.metadata["emit_ws"])

    def test_credentials_updated_clear_flag(self) -> None:
        event = CredentialsUpdatedEvent(
            connection_id="acc-1",
            provider="whatsapp",
            credentials={},
            clear=True,
        )
        self.assertTrue(event.clear)

    def test_connection_state_event(self) -> None:
        event = ConnectionStateEvent(
            connection_id="acc-1",
            provider="discord",
            state="authorized",
            error="",
            metadata={"gateway": "ready"},
        )
        self.assertEqual(event.state, "authorized")
        self.assertEqual(event.metadata["gateway"], "ready")

    def test_chats_discovered_runtime_is_opaque(self) -> None:
        runtime = object()
        event = ChatsDiscoveredEvent(
            connection_id="acc-1",
            provider="telegram",
            chats=[{"external_chat_id": "1", "title": "Chat"}],
            runtime=runtime,
        )
        self.assertIs(event.runtime, runtime)
        self.assertEqual(len(event.chats), 1)

    def test_chat_id_remap_event(self) -> None:
        event = ChatIdRemapEvent(
            connection_id="acc-1",
            provider="whatsapp",
            chat_key="lid:abc",
            external_chat_id="79990001122",
        )
        self.assertEqual(event.chat_key, "lid:abc")


if __name__ == "__main__":
    unittest.main()
