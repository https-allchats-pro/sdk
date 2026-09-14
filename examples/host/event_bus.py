"""Minimal host example: public Message DTO → in-memory Event Bus → feature handler.

Shows how a host maps SDK domain objects without deep-importing event internals.

Run from the allchats-sdk directory:

    python examples/host/event_bus.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from allchats_sdk import Message


# --- tiny Event Bus (mirrors backend internal.event_bus) ---


@dataclass(frozen=True, slots=True)
class MessageReceived:
    provider: str
    account_id: str
    chat_id: str
    message_id: str
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
        self.seen.append(event.message_id)
        print(f"[crm] message {event.message_id}: {event.text!r}")


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


# --- Host adapter: public Message → domain bus ---


class HostMessageBridge:
    """Maps public :class:`~allchats_sdk.Message` into the host event bus."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def publish_incoming(self, message: Message) -> None:
        await self._bus.publish(
            MessageReceived(
                provider=message.provider,
                account_id=message.account_id,
                chat_id=message.chat_id,
                message_id=message.id,
                text=message.text,
                from_id=message.from_id,
                sent_at=message.sent_at or datetime.now(UTC),
            )
        )


async def main() -> None:
    bus = EventBus()
    registry = FeatureRegistry()
    crm = CrmFeature()

    await registry.start_enabled(
        {"crm": True, "broadcast": False},
        [crm],
        bus,
    )

    bridge = HostMessageBridge(bus)
    await bridge.publish_incoming(
        Message(
            id="msg-42",
            chat_id="chat-1",
            account_id="acc-1",
            provider="telegram",
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
