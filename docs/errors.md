# Errors

All public errors inherit from `AllChatsError` (`MessengerError` is an alias).

| Exception | When |
|-----------|------|
| `AllChatsError` | Base type for catching SDK failures |
| `ValidationError` | Invalid input / missing provider config |
| `MessengerClientUnavailableError` | Provider / session not ready (e.g. MAX runtime missing) |
| `SessionNotConnectedError` | Session status is not connected |
| `UnsupportedCapabilityError` | Capability group or method not available |

```python
from allchats_sdk import AllChatsError
from allchats_sdk.errors import UnsupportedCapabilityError, ValidationError

try:
    await client.messages.send("hi", chat_id="1")
except UnsupportedCapabilityError as exc:
    print(exc.provider, exc.capability)
except ValidationError:
    ...
except AllChatsError:
    ...
```

## Auth / connection

- Missing Telegram `app_id` / `app_hash` → `ValidationError` (or `SystemExit` in examples).
- MAX without a connected runtime → `MessengerClientUnavailableError`.
- Missing auth method on a provider → `UnsupportedCapabilityError` with a capability
  string such as `auth.start_qr` or `auth.connect_with_token`.

## Provider-specific

```python
from allchats_sdk.errors import is_telegram_rpc_error

try:
    ...
except Exception as exc:
    if is_telegram_rpc_error(exc):
        ...
```

`is_telegram_rpc_error` returns `False` if the `[telegram]` extra (Telethon) is
not installed.

VK / other providers may raise their own exceptions (`VkApiError`, etc.) from
provider modules — catch them when calling low-level helpers; prefer
`AllChatsError` at application boundaries for the public client API.
