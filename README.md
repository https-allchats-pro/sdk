# AllChats SDK

Universal Python SDK for messenger integrations.

Connect Telegram, VK, MAX (and more) with one account-oriented API: auth, send,
receive, and session persistence — without FastAPI, PostgreSQL, or app domain code.

## Installation

```bash
pip install allchats-sdk
pip install "allchats-sdk[telegram]"
pip install "allchats-sdk[vk]"
pip install "allchats-sdk[max]"
pip install "allchats-sdk[telegram,vk,max]"
```

The base package is minimal (clients, models, credential store). Messenger
runtimes are optional extras.

Requires **Python 3.11+**.

## Quick start

```python
import asyncio
from allchats_sdk.telegram import TelegramClient
from allchats_sdk import FileCredentialStore

async def main() -> None:
    store = FileCredentialStore("./telegram-session.json")
    client = TelegramClient(
        account_id="acc-1",
        app_id=12345,          # https://my.telegram.org/apps
        app_hash="your_app_hash",
        credential_store=store,
    )

    await client.auth.start_qr()
    status = await client.auth.wait_until_authorized(
        password_provider=lambda: input("2FA password: "),
    )
    print("authorized", status.user_id)

    await client.connect()
    message_id, chat_id = await client.messages.send("hello", chat_id="123456789")
    print("sent", message_id, chat_id)
    await client.disconnect()

asyncio.run(main())
```

Same idea for VK:

```python
from allchats_sdk.vk import VKClient
from allchats_sdk import FileCredentialStore

store = FileCredentialStore("./vk-session.json")
client = VKClient(account_id="acc-1", app_id="12345678", credential_store=store)
await client.auth.start_qr()
await client.auth.wait_until_authorized()
```

Runnable scripts: [`examples/`](examples/README.md).

## Features

- **Account clients** — `TelegramClient`, `VKClient`, `MAXClient`
- **Session persistence** — `FileCredentialStore` / `MemoryCredentialStore` (no custom sink required)
- **Typed auth state** — `ConnectionState`, `wait_until_authorized(...)`
- **Capabilities** — `client.auth`, `client.messages`, `client.chats`
- **Optional EventSink** — observe incoming/outgoing messages when you need them
- **Host protocols** — plug into a backend (`EventSink`, media, delivery) without coupling the SDK to your app

## Supported messengers

| Messenger | Extra | Auth | Notes |
|-----------|-------|------|--------|
| Telegram | `[telegram]` | QR, 2FA password | Preferred public API |
| VK | `[vk]` | QR, token, VK ID OAuth | Preferred public API |
| MAX | `[max]` | QR, SMS | Needs host `SessionManager` as `session_host` |
| WhatsApp | `[whatsapp]` | QR (neonize) | Advanced / host |
| Discord | `[discord]` | QR, login | Advanced / host |
| Avito | `[avito]` | OAuth | Advanced / host |

```bash
pip install "allchats-sdk[all]"   # every extra
```

## Authentication

### Telegram (QR)

```python
from allchats_sdk.telegram import TelegramClient
from allchats_sdk import FileCredentialStore

store = FileCredentialStore("./telegram-session.json")
client = TelegramClient(
    account_id="acc-1",
    app_id=12345,
    app_hash="…",
    credential_store=store,
)

qr = await client.auth.start_qr()
print(qr.qr_link)  # scan in Telegram → Devices

status = await client.auth.wait_until_authorized(
    password_provider=lambda: input("2FA password: "),
)
# status.state == ConnectionState.AUTHORIZED
```

Reconnect later (session already on disk):

```python
status = await client.connect()  # loads from credential_store
```

### VK

```python
from allchats_sdk.vk import VKClient

client = VKClient(account_id="acc-1", app_id="…", credential_store=store)

await client.auth.start_qr()
# or: await client.auth.connect_with_token(access_token)
# or: url = client.auth.build_oauth_url(); … connect_with_oauth_code(...)

await client.auth.wait_until_authorized()
```

### MAX

MAX sessions are owned by the host application:

```python
from allchats_sdk.max import MAXClient

client = MAXClient(account_id="acc-1", session_host=session_manager)
await client.connect()
await client.auth.start_qr(credentials)
```

See [`examples/max/`](examples/max/).

## Sending messages

```python
await client.connect()

message_id, chat_id = await client.messages.send(
    "hello",
    chat_id="123456789",
)
```

Telegram also accepts `phone_number=` where supported by the provider.
Catch `AllChatsError` (and subclasses) at application boundaries.

## Receiving events

Pass an `event_sink` to observe traffic. Credentials still persist via
`credential_store`.

```python
class PrintIncoming:
    async def on_incoming(self, event) -> None:
        print(f"{event.external_chat_id} ← {event.from_id}: {event.text}")

    async def on_outgoing(self, event) -> None: ...
    async def on_credentials_updated(self, event) -> None: ...
    async def on_connection_state(self, event) -> None: ...
    async def on_chats_discovered(self, event) -> None: ...
    async def on_chat_id_remap(self, event) -> None: ...

client = TelegramClient(
    ...,
    credential_store=store,
    event_sink=PrintIncoming(),
)
await client.connect()
# keep the process running while the provider listens
```

Full example: [`examples/telegram/receive_messages.py`](examples/telegram/receive_messages.py).

Hosts that need rich media (voice/files) implement `IncomingMessageHandler` /
`MediaStorage` from `allchats_sdk.protocols`.

## Architecture

```text
Your app
  └── TelegramClient / VKClient / MAXClient
        └── Provider (TelegramProvider, …)
              └── messenger network (Telethon, vk-api, …)

Optional host (backend)
  └── implements protocols (EventSink, MediaStorage, …)
```

- **Public:** `allchats_sdk`, `allchats_sdk.telegram`, `.vk`, `.max`
- **Internal:** `allchats_sdk.internal.*` (registry, hooks, observability, runtime)
- Dependency direction is always **app/host → SDK → external APIs** — the SDK never imports your application code.

Stack for Telegram:

```text
TelegramClient → TelegramProvider → MessengerClient → Telethon
                     ↑
              CredentialStore / PersistingEventSink
```

## Development

```bash
git clone https://github.com/https-allchats-pro/sdk.git
cd sdk
pip install -e ".[all,dev]"
pytest
```

```text
tests/
├── unit/
├── providers/
└── integration/
```

Examples and local install from a monorepo checkout:

```bash
pip install -e "./allchats-sdk[telegram,vk]"
python examples/telegram/connect_qr.py
```

### Publishing

```bash
pip install -e ".[dev]"
python -m build
twine check dist/*
twine upload --repository testpypi dist/*   # TestPyPI
twine upload dist/*                         # PyPI
```

Use API tokens (`username = __token__`). Never commit tokens.

### Versioning

SemVer. Current version: **0.1.0**.

## License

MIT — see [LICENSE](LICENSE).
