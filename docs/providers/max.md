# MAX

Public client: `MAXClient` / `MAXProvider`.

**Status: host-backed.** Sessions are owned by a host `SessionManager` (or
compatible `session_host`). Standalone QR without a host is not supported.

## Installation

```bash
pip install "allchats-sdk[max]"
```

## Authentication

```python
from allchats_sdk.max import MAXClient

client = MAXClient(account_id="acc-1", session_host=session_manager)
await client.auth.start_qr(credentials)
```

`credentials` shape depends on the host (e.g. `device_id`, tokens).

## Connecting

```python
await client.connect()  # delegates to session_host.connect_account
```

## Sending messages

```python
result = await client.messages.send("hello", chat_id="12345")
# phone_number= if the host implements send_message_by_phone
```

## Receiving messages

Incoming traffic is delivered through the host (`notify_incoming_message`), not
via `EventSink.on_incoming` on `MAXProvider`.

## Supported capabilities

| Capability | Status |
|------------|--------|
| Public `MAXClient` | ⚠️ requires `session_host` |
| Auth / send / disconnect | ⚠️ delegated to host |
| EventSink receive | ❌ |
| Chats (`client_for_account` → host runtime) | ⚠️ |
| Media helpers in package | ✅ |
| Builtin registry | ❌ |

## Limitations

- Not registered in `register_builtin_providers`.
- Examples under `examples/max/` are templates: wire `get_session_host()`.

## Known issues

- `wait_until_authorized` on the legacy MAX authenticator path may raise
  `UnsupportedCapabilityError` depending on wiring; prefer host-level auth UX.
