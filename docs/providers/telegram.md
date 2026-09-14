# Telegram

First-class public client: `TelegramClient` / `TelegramProvider`.

## Installation

```bash
pip install "allchats-sdk[telegram]"
```

App credentials: https://my.telegram.org/apps

```bash
export TELEGRAM_APP_ID=…
export TELEGRAM_APP_HASH=…
```

## Authentication

QR (+ optional 2FA password):

```python
from allchats_sdk.telegram import TelegramClient
from allchats_sdk import FileCredentialStore

store = FileCredentialStore("./telegram-session.json")
client = TelegramClient(
    account_id="acc-1",
    app_id=int(os.environ["TELEGRAM_APP_ID"]),
    app_hash=os.environ["TELEGRAM_APP_HASH"],
    credential_store=store,
)
await client.auth.start_qr()
await client.auth.wait_until_authorized(
    password_provider=lambda: input("2FA password: "),
)
```

## Connecting

```python
status = await client.connect()  # loads session from credential_store
```

## Sending messages

```python
message_id, chat_id = await client.messages.send(
    "hello",
    chat_id="123456789",
)
# phone_number= is also accepted by the provider when applicable
```

## Receiving messages

Pass `event_sink=` implementing `EventSink` (see [events.md](../events.md)).
Example: `examples/telegram/receive_messages.py`.

## Supported capabilities

| Capability | Status |
|------------|--------|
| `auth` (QR, password, connect/disconnect) | ✅ |
| `messages.send` | ✅ |
| `chats.client_state` | ✅ |
| `chats.sync` | ⚠️ may raise if no sync helper is used |
| Media (voice/files via workers + metadata) | ✅ |
| Builtin registry | ✅ |

## Limitations

- Requires Telethon (`[telegram]` extra).
- Voice/calls helpers exist under `providers.telegram` but are advanced APIs.

## Known issues

- None tracked specifically for `0.1.1` polish; report via GitHub Issues.
