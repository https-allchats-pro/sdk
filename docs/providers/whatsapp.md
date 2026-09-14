# WhatsApp

**Status: manager / host integration.** There is no public `WhatsAppClient`
account facade yet.

## Installation

```bash
pip install "allchats-sdk[whatsapp]"
```

## Authentication

Implemented on `WhatsAppClientManager` (`start_qr`, `connect_account`, …).
Prefer host wiring or SDK extension code; not the recommended end-user path.

## Connecting / sending / receiving

Manager supports `connect_account`, `send_message`, and EventSink incoming via
`neonize_runtime`. Registered in the builtin registry as `"whatsapp"`.

## Supported capabilities

| Capability | Status |
|------------|--------|
| Public account client | ❌ |
| Manager auth / send / receive | ✅ |
| Media helpers | ✅ |
| Builtin registry | ✅ |

## Limitations

- Depends on neonize / protobuf extras.
- No first-class examples under `examples/` for end users yet.

## Known issues

- Treat as advanced until a public client lands.
