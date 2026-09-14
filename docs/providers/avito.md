# Avito

**Status: manager / host integration.** No public `AvitoClient` facade yet.

## Installation

```bash
pip install "allchats-sdk[avito]"
```

## Authentication

`AvitoClientManager` supports OAuth / key flows (`connect_with_keys`,
`connect_with_oauth_code`, `connect_account`). No QR auth.

## Connecting / sending / receiving

Manager implements `send_message` and EventSink incoming via `sync_worker`.
Registered as `"avito"`.

## Supported capabilities

| Capability | Status |
|------------|--------|
| Public account client | ❌ |
| Manager auth / send / receive | ✅ |
| Media helpers | ✅ |
| Builtin registry | ✅ |

## Limitations

- No first-class end-user examples yet.

## Known issues

- Treat as advanced until a public client lands.
