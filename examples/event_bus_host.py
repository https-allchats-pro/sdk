"""Minimal host example: SDK EventSink → in-memory Event Bus → feature handler.

Run from the allchats-sdk directory:

    python examples/event_bus_host.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable


# --- tiny Event Bus (mirrors backend internal.event_bus) ---


@dataclass(frozen=True, slots=True)
class MessageReceived:
    provider: str
    connection_id: str
    external_chat_id: str
    external_message_id: str
    text: str
    from_id: str = ""
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Any], list[Callable[[Any], Awaitable[None]]]] = {}

    def subscribe(self, event_type: type[Any], handler: Callable[[Any], Awaitable[None]]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: object) -> None:
        for handler in self._handlers.get(type(event), []):
            await handler(event)


# --- Feature registry sketch ---


class CrmFeature:
    name = "crm"

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def setup(self, bus: EventBus) -> None:
        bus.subscribe(MessageReceived, self._on_message)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def _on_message(self, event: MessageReceived) -> None:
        self.seen.append(event.external_message_id)
        print(f"[crm] message {event.external_message_id}: {event.text!r}")


class FeatureRegistry:
    def __init__(self) -> None:
        self._started: list[Any] = []

    async def start_enabled(
        self,
        enabled: dict[str, bool],
        features: list[Any],
        bus: EventBus,
    ) -> None:
        for feature in features:
            if not enabled.get(feature.name, False):
                print(f"skip disabled feature={feature.name}")
                continue
            await feature.setup(bus)
            await feature.start()
            self._started.append(feature)
            print(f"started feature={feature.name}")

    async def stop_all(self) -> None:
        for feature in reversed(self._started):
            await feature.stop()
        self._started.clear()


# --- SDK EventSink adapter ---


class HostEventSink:
    """Implements allchats_sdk EventSink; publishes domain events."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def on_incoming(self, event: Any) -> None:
        await self._bus.publish(
            MessageReceived(
                provider=event.provider,
                connection_id=event.connection_id,
                external_chat_id=event.external_chat_id,
                external_message_id=event.external_message_id,
                text=event.text,
                from_id=event.from_id,
                sent_at=event.sent_at or datetime.now(UTC),
            )
        )

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


async def main() -> None:
    from allchats_sdk.events import IncomingMessageEvent

    bus = EventBus()
    registry = FeatureRegistry()
    crm = CrmFeature()

    # Config: CRM on, broadcast off — disabled module never starts.
    await registry.start_enabled(
        {"crm": True, "broadcast": False},
        [crm],
        bus,
    )

    sink = HostEventSink(bus)
    await sink.on_incoming(
        IncomingMessageEvent(
            connection_id="acc-1",
            provider="telegram",
            external_chat_id="chat-1",
            external_message_id="msg-42",
            from_id="user-7",
            text="hello from SDK",
            sent_at=datetime.now(UTC),
        )
    )

    assert crm.seen == ["msg-42"]
    await registry.stop_all()
    print("ok")


if __name__ == "__main__":
    asyncio.run(main())
