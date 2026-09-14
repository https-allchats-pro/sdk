# AllChats SDK

Unified Python SDK for messaging platforms.

Connect Telegram, VK, MAX, and other messengers through one account-oriented API:
authenticate, send, receive events, and persist sessions — without FastAPI or a database.

[![PyPI](https://img.shields.io/pypi/v/allchats-sdk.svg)](https://pypi.org/project/allchats-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/allchats-sdk.svg)](https://pypi.org/project/allchats-sdk/)
[![CI](https://github.com/https-allchats-pro/sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/https-allchats-pro/sdk/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Installation

```bash
pip install allchats-sdk

# provider-specific integrations
pip install "allchats-sdk[telegram]"
pip install "allchats-sdk[vk]"
pip install "allchats-sdk[max]"
pip install "allchats-sdk[telegram,vk]"
```

Requires **Python 3.11+**. The base install is minimal; messenger runtimes are optional extras.

## Quick start

```python
import asyncio
from allchats_sdk.telegram import TelegramClient
from allchats_sdk import FileCredentialStore

async def main() -> None:
    store = FileCredentialStore("./telegram-session.json")
    client = TelegramClient(
        account_id="acc-1",
        app_id=12345,  # https://my.telegram.org/apps
        app_hash="your_app_hash",
        credential_store=store,
    )

    await client.auth.start_qr()
    await client.auth.wait_until_authorized(
        password_provider=lambda: input("2FA password: "),
    )

    await client.connect()
    message_id, chat_id = await client.messages.send("hello", chat_id="123456789")
    print(message_id, chat_id)
    await client.disconnect()

asyncio.run(main())
```

More scripts: [`examples/`](examples/README.md).

## Supported messengers

| Provider | Extra | Public client | Status |
|----------|-------|---------------|--------|
| Telegram | `[telegram]` | `TelegramClient` | First-class |
| VK | `[vk]` | `VKClient` | First-class |
| MAX | `[max]` | `MAXClient` | Host `session_host` required |
| WhatsApp | `[whatsapp]` | — | Manager / host (no public client yet) |
| Discord | `[discord]` | — | Manager / host (no public client yet) |
| Avito | `[avito]` | — | Manager / host (no public client yet) |

Capability details: [`docs/capabilities.md`](docs/capabilities.md).

## Capabilities

Account clients expose capability groups via properties:

```python
client.auth       # connect, QR, disconnect, …
client.messages   # send
client.chats      # client_state / sync (when supported)

from allchats_sdk import Capability
list(Capability)  # messages, chats, auth
```

Unsupported groups raise `UnsupportedCapabilityError`. There is no `client.capabilities` list API — probe the properties you need.

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting started](docs/getting-started.md) | Install → connect → send / receive |
| [Architecture](docs/architecture.md) | Public vs internal layers |
| [Authentication](docs/authentication.md) | QR, token, OAuth, MAX host |
| [Events](docs/events.md) | `EventSink` and event types |
| [Capabilities](docs/capabilities.md) | Matrix + how to probe |
| [Credentials](docs/credentials.md) | Stores and sanitization |
| [Errors](docs/errors.md) | Exception hierarchy |
| [Security](docs/security.md) | Sessions, logging, reporting |
| [Providers](docs/providers/) | Per-messenger notes |

## Security

Do not commit session files or tokens. See [`SECURITY.md`](SECURITY.md) and [`docs/security.md`](docs/security.md).

## Contributing

```bash
git clone https://github.com/https-allchats-pro/sdk.git
cd sdk
pip install -e ".[all,dev]"
pytest
```

- Prefer public imports (`allchats_sdk`, `allchats_sdk.telegram`, …).
- Do not rely on `allchats_sdk.internal` in application code.
- Open a PR against `main`; CI must pass.

## License

MIT — see [LICENSE](LICENSE).
