# Getting started

From install to a first message with Telegram (same pattern for VK).

## 1. Install

```bash
pip install "allchats-sdk[telegram]"
```

## 2. App credentials

Create an application at https://my.telegram.org/apps and export:

```bash
export TELEGRAM_APP_ID=12345
export TELEGRAM_APP_HASH=your_app_hash
```

## 3. Create a client with a credential store

```python
import os
from allchats_sdk.telegram import TelegramClient
from allchats_sdk import FileCredentialStore

store = FileCredentialStore("./telegram-session.json")
client = TelegramClient(
    account_id="acc-1",
    app_id=int(os.environ["TELEGRAM_APP_ID"]),
    app_hash=os.environ["TELEGRAM_APP_HASH"],
    credential_store=store,
)
```

`credential_store` persists the session automatically after QR / 2FA. You do not need a custom `EventSink` for normal login.

## 4. Authenticate

```python
await client.auth.start_qr()
# print / display qr.qr_link and scan in Telegram → Devices

status = await client.auth.wait_until_authorized(
    password_provider=lambda: input("2FA password: "),
)
print(status.user_id, status.state)
```

Later sessions:

```python
status = await client.connect()  # loads from the store
```

## 5. Receive events (optional)

```python
class PrintIncoming:
    async def on_incoming(self, event) -> None:
        print(event.text)

    async def on_outgoing(self, event) -> None: ...
    async def on_credentials_updated(self, event) -> None: ...
    async def on_connection_state(self, event) -> None: ...
    async def on_chats_discovered(self, event) -> None: ...
    async def on_chat_id_remap(self, event) -> None: ...

client = TelegramClient(..., credential_store=store, event_sink=PrintIncoming())
await client.connect()
# keep the process alive while the provider listens
```

## 6. Send a message

```bash
export TELEGRAM_CHAT_ID=123456789
```

```python
await client.connect()
message_id, chat_id = await client.messages.send("hello", chat_id=os.environ["TELEGRAM_CHAT_ID"])
await client.disconnect()
```

## Runnable examples

```bash
python examples/telegram/connect_qr.py
python examples/telegram/reconnect.py
python examples/telegram/send_message.py "hi"
python examples/telegram/receive_messages.py
python examples/telegram/inspect_capabilities.py
```

See [examples/README.md](../examples/README.md) and [providers/telegram.md](providers/telegram.md).
