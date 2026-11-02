"""WhatsApp protobuf field presence and message unwrap tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from allchats_sdk.providers.whatsapp.client import (
    extract_message_text,
    history_sync_contains_messages,
    is_skippable_whatsapp_chat,
    is_whatsapp_outgoing_message,
    proto_field_present,
    unwrap_whatsapp_message,
)
from allchats_sdk.providers.whatsapp.media import detect_whatsapp_media_type
from allchats_sdk.reactions import parse_whatsapp_reaction_message


class _Descriptor:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeProto:
    def __init__(self, **fields: object) -> None:
        self._fields = fields
        for key, value in fields.items():
            setattr(self, key, value)

    def HasField(self, name: str) -> bool:
        return name in self._fields

    def ListFields(self):
        return [(_Descriptor(name), value) for name, value in self._fields.items()]

    def __getattr__(self, name: str) -> FakeProto:
        return FakeProto()


class WhatsAppProtoFieldTests(unittest.TestCase):
    def test_text_message_is_not_treated_as_media(self) -> None:
        message = FakeProto(conversation="hello")
        self.assertTrue(proto_field_present(message, "conversation"))
        self.assertFalse(proto_field_present(message, "audioMessage"))
        self.assertIsNone(detect_whatsapp_media_type(message))
        self.assertEqual(extract_message_text(message), "hello")

    def test_empty_device_sent_wrapper_is_ignored(self) -> None:
        message = FakeProto(conversation="hello")
        self.assertIs(unwrap_whatsapp_message(message), message)
        self.assertFalse(is_whatsapp_outgoing_message(SimpleNamespace(IsFromMe=False), message))

    def test_real_device_sent_message_is_outgoing(self) -> None:
        inner = FakeProto(conversation="from other device")
        message = FakeProto(deviceSentMessage=FakeProto(message=inner))
        self.assertTrue(is_whatsapp_outgoing_message(SimpleNamespace(IsFromMe=False), message))
        self.assertEqual(extract_message_text(message), "from other device")

    def test_reaction_requires_set_field(self) -> None:
        message = FakeProto(conversation="hello")
        self.assertIsNone(parse_whatsapp_reaction_message(message))

    def test_skippable_chats(self) -> None:
        self.assertTrue(is_skippable_whatsapp_chat("status@broadcast"))
        self.assertTrue(is_skippable_whatsapp_chat("123@newsletter"))
        self.assertFalse(is_skippable_whatsapp_chat("79951234567@s.whatsapp.net"))
        self.assertFalse(is_skippable_whatsapp_chat("120363@g.us"))

    def test_history_sync_type_filter(self) -> None:
        self.assertTrue(history_sync_contains_messages("INITIAL_BOOTSTRAP"))
        self.assertTrue(history_sync_contains_messages(0))
        self.assertTrue(history_sync_contains_messages(3))
        self.assertFalse(history_sync_contains_messages("PUSH_NAME"))
        self.assertFalse(history_sync_contains_messages("INITIAL_STATUS_V3"))
        self.assertFalse(history_sync_contains_messages(4))


if __name__ == "__main__":
    unittest.main()
