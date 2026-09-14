# Events

Providers push events to an optional `EventSink`. Account clients wrap your sink
with credential persistence when `credential_store=` is set.

## EventSink

Implement all methods (duck-typed protocol):

```python
class PrintIncoming:
    async def on_incoming(self, event) -> None:
        print(event.provider, event.external_chat_id, event.text)

    async def on_outgoing(self, event) -> None:
        return None

    async def on_credentials_updated(self, event) -> None:
        return None

    async def on_connection_state(self, event) -> None:
        return None

    async def on_chats_discovered(self, event) -> None:
        return None

    async def on_chat_id_remap(self, event) -> None:
        return None
```

Pass it as `event_sink=PrintIncoming()` to `TelegramClient` / `VKClient`.

## Event types

Defined in `allchats_sdk.events`:

| Event | Purpose |
|-------|---------|
| `IncomingMessageEvent` | Inbound message (+ `metadata` for media fields) |
| `OutgoingMessageEvent` | Outbound message |
| `CredentialsUpdatedEvent` | Persist or clear session credentials |
| `ConnectionStateEvent` | Auth / runtime state changes |
| `ChatsDiscoveredEvent` | Chat/channel sync |
| `ChatIdRemapEvent` | e.g. WhatsApp LID↔PN remaps |

Common `IncomingMessageEvent.metadata` keys (when present):
`message_type`, `media_path`, `duration_ms`, `media_filename`, `grouped_id`,
`from_name`, `avatar_url`.

## Host media pipeline

Rich media may also go through `IncomingMessageHandler` / `MediaStorage` from
`allchats_sdk.protocols` when the host implements them. The SDK does not require
a database.

## MAX note

MAX incoming traffic is delivered through the host session manager, not through
a standalone `EventSink.on_incoming` path on `MAXProvider`.
