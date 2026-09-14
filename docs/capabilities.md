# Capabilities

## High-level groups

`Capability` enum (`allchats_sdk.models`) lists the groups exposed by
`MessengerClient`:

| Value | Access | Typical methods |
|-------|--------|-----------------|
| `messages` | `client.messages` | `send(...)` |
| `chats` | `client.chats` | `client_state()`, `sync()` |
| `auth` | `client.auth` | `start_qr`, `connect`, `disconnect`, … |

There is **no** `client.capabilities` property. Probe by using the property; if
unsupported, `UnsupportedCapabilityError` is raised.

```python
from allchats_sdk import Capability, UnsupportedCapabilityError

print(list(Capability))  # [<Capability.MESSAGES: 'messages'>, ...]

try:
    sender = client.messages
except UnsupportedCapabilityError as exc:
    print(exc.provider, exc.capability)
```

Account clients (`TelegramClient`, …) forward the same properties.

## Capability matrix

Based on the current codebase (not aspirational).

Legend: ✅ supported · ⚠️ partial · ❌ unsupported · — n/a

| Provider | Public client | Auth | Send | Receive (`EventSink`) | Chats | Media helpers | Builtin registry |
|----------|---------------|------|------|------------------------|-------|---------------|------------------|
| Telegram | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| VK | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| MAX | ⚠️ host `session_host` | ⚠️ host-backed | ⚠️ host-backed | ❌ (host notify path) | ⚠️ runtime lookup | ✅ | ❌ |
| WhatsApp | ❌ (manager only) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Discord | ❌ (manager only) | ✅ | ✅ | ✅ | ✅ | ⚠️ voice-focused | ✅ |
| Avito | ❌ (manager only) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### Notes

- **Public client**: first-class `*Client` export for end users.
- **Receive**: provider calls `EventSink.on_incoming`. MAX uses host
  `notify_incoming_message` instead.
- **Chats**: `MessengerClient.chats` works when the provider exposes
  `client_for_account` (and optionally sync helpers). `sync()` may still raise
  `UnsupportedCapabilityError` if the provider has no sync method.
- **Media helpers**: provider modules for download/upload exist; delivery to your
  app is via events / host handlers, not a separate `Capability` enum value.
- **Registry**: `register_builtin_providers` — MAX is intentionally omitted.

See also [providers/](providers/) for per-messenger status.
