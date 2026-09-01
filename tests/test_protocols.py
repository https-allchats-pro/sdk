"""Protocol and NullEventSink tests."""

from __future__ import annotations

import unittest
from typing import Any

from allchats_sdk.capabilities import ChatReader, MessageSender, MessengerAuthenticator
from allchats_sdk.events import IncomingMessageEvent
from allchats_sdk.host_ports import (
    CredentialStorage,
    DeliveryTracker,
    IncomingMessageHandler,
    MediaStorage,
)
from allchats_sdk.protocols import EventSink, MessengerProvider, NullEventSink


class _RecordingEventSink:
    def __init__(self) -> None:
        self.incoming: list[IncomingMessageEvent] = []

    async def on_incoming(self, event: IncomingMessageEvent) -> None:
        self.incoming.append(event)

    async def on_outgoing(self, event: Any) -> None:
        return None

    async def on_credentials_updated(self, event: Any) -> None:
        return None

    async def on_connection_state(self, event: Any) -> None:
        return None

    async def on_chats_discovered(self, event: Any) -> None:
        return None

    async def on_chat_id_remap(self, event: Any) -> None:
        return None


class _MediaStorageImpl:
    def save_voice(self, *, account_id: str, data: bytes, extension: str) -> str:
        return f"/voice/{account_id}{extension}"

    def save_media(self, *, account_id: str, data: bytes, extension: str) -> str:
        return f"/media/{account_id}{extension}"

    def save_avatar(self, *, account_id: str, external_chat_id: str, data: bytes) -> str:
        return f"/avatar/{account_id}/{external_chat_id}"


class _DeliveryTrackerImpl:
    async def mark_up_to_external_id(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        max_external_id: int,
        status: str,
    ) -> None:
        return None

    async def mark_by_external_ids(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        external_ids: list[str],
        status: str,
    ) -> None:
        return None

    async def mark_up_to_sent_at(
        self,
        account_id: str,
        *,
        external_chat_id: str,
        sent_before: Any,
        status: str,
    ) -> None:
        return None


class _IncomingHandlerImpl:
    async def process_telegram_incoming(self, **kwargs: Any) -> bool:
        return True

    async def process_telegram_outgoing(self, **kwargs: Any) -> Any | None:
        return None

    async def process_vk_incoming(self, **kwargs: Any) -> bool:
        return True

    async def process_vk_outgoing(self, **kwargs: Any) -> Any | None:
        return None

    async def process_whatsapp_incoming(self, **kwargs: Any) -> bool:
        return True

    async def process_whatsapp_outgoing(self, **kwargs: Any) -> Any | None:
        return None

    async def process_max_incoming(self, **kwargs: Any) -> Any | None:
        return None

    async def process_max_outgoing(self, **kwargs: Any) -> Any | None:
        return None


class _CredentialStorageImpl:
    async def get(self, account_id: str) -> dict[str, Any] | None:
        return {"account_id": account_id}

    async def save(self, account_id: str, credentials: dict[str, Any]) -> None:
        return None

    async def clear(self, account_id: str) -> None:
        return None


class _MessageSenderImpl:
    async def send(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        phone_number: str | None = None,
        reply_to_external_id: str | None = None,
        **kwargs: Any,
    ) -> tuple[str, str]:
        return ("1", chat_id or "")


class _ChatReaderImpl:
    async def client_state(self) -> Any:
        return {"state": "ok"}

    async def sync(self) -> Any:
        return 0


class _AuthenticatorImpl:
    async def connect(self, credentials: dict[str, Any]) -> Any:
        return credentials

    async def start_qr(self, credentials: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return {"qr": "link"}

    async def disconnect(self) -> None:
        return None


class ProtocolTests(unittest.TestCase):
    def test_null_event_sink_is_event_sink(self) -> None:
        sink = NullEventSink()
        self.assertIsInstance(sink, EventSink)

    def test_recording_sink_is_event_sink(self) -> None:
        sink = _RecordingEventSink()
        self.assertIsInstance(sink, EventSink)

    def test_host_port_implementations(self) -> None:
        self.assertIsInstance(_MediaStorageImpl(), MediaStorage)
        self.assertIsInstance(_DeliveryTrackerImpl(), DeliveryTracker)
        self.assertIsInstance(_IncomingHandlerImpl(), IncomingMessageHandler)
        self.assertIsInstance(_CredentialStorageImpl(), CredentialStorage)

    def test_capability_protocols(self) -> None:
        self.assertIsInstance(_MessageSenderImpl(), MessageSender)
        self.assertIsInstance(_ChatReaderImpl(), ChatReader)
        self.assertIsInstance(_AuthenticatorImpl(), MessengerAuthenticator)

    def test_messenger_provider_protocol_is_structural(self) -> None:
        class _Provider:
            provider_id = "mock"

            async def connect(self, connection_id: str, credentials: dict[str, Any]) -> Any:
                return credentials

            async def disconnect(self, connection_id: str) -> None:
                return None

            async def send_message(
                self,
                connection_id: str,
                chat_id: str,
                text: str,
                **kwargs: Any,
            ) -> Any:
                return text

            async def get_dialogs(self, connection_id: str) -> list[Any]:
                return []

        self.assertIsInstance(_Provider(), MessengerProvider)


if __name__ == "__main__":
    unittest.main()
