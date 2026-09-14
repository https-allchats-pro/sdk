# allchats-sdk

Python SDK for messenger integrations (Telegram, VK, MAX, Avito, Discord, WhatsApp).

Standalone package extracted from the AllChats backend. Does not depend on FastAPI, PostgreSQL, or application domain logic.

## Architecture

```text
Backend (host)
    │
    ├── implements host ports (MediaStorage, DeliveryTracker, IncomingMessageHandler, EventSink)
    ├── uses MessengerClient / provider managers
    ▼
allchats-sdk
    ├── ProviderRegistry + built-in providers
    ├── events → EventSink
    └── provider-specific clients (Telethon, vk-api, neonize, …)
```

Dependency direction is always **backend → allchats-sdk → external APIs**. The SDK never imports application code.

## Installation

From monorepo root:

```bash
pip install -e "./allchats-sdk[all]"
```

With specific providers:

```bash
pip install -e "./allchats-sdk[telegram,vk]"
```

For development and tests:

```bash
pip install -e "./allchats-sdk[all,dev]"
```

## Public API

Preferred **account clients** with automatic session persistence:

```python
from allchats_sdk.telegram import TelegramClient
from allchats_sdk import FileCredentialStore

store = FileCredentialStore("./telegram-session.json")
client = TelegramClient(
    account_id="acc-1",
    app_id=12345,
    app_hash="...",
    credential_store=store,
)
await client.auth.start_qr()
status = await client.auth.wait_until_authorized(
    password_provider=lambda: input("2FA password: "),
)
# status.state is ConnectionState.AUTHORIZED
await client.connect()  # loads credentials from store
```

Equivalent root import: ``from allchats_sdk import TelegramClient``.
Provider shortcuts: ``allchats_sdk.telegram``, ``allchats_sdk.vk``, ``allchats_sdk.max``.

You do **not** need a custom ``EventSink`` or manual credential extraction for normal usage.
Pass ``event_sink=`` only when the host must observe messages/state.

Stack inside the SDK:

```text
TelegramClient → TelegramProvider → MessengerClient → Telegram
                     ↑
              CredentialStore (FileCredentialStore / MemoryCredentialStore)
```

Also exported (advanced / host wiring):

```python
from allchats_sdk import (
    MessengerClient,
    TelegramProvider,
    VKProvider,
    MAXProvider,
    Message,
    Chat,
    Account,
    ConnectionState,
    Capability,
    AllChatsError,
)
```

`MaxMessengerClient` remains a thin alias around ``MAXProvider`` / ``MAXClient``.

Non-public modules live under ``allchats_sdk.internal`` (registry, hooks,
observability, runtime). Application code should not import them unless you are
extending the SDK or wiring a host. Legacy top-level paths
(``allchats_sdk.registry``, ``hooks``, ``observability``, ``host``) remain as shims.

## Domain models

Public DTOs live in a single ``models.py`` (`Message`, `Chat`, `Account`,
`ConnectionState`, `ConnectionStatus`, `Capability`). We only split into a
``models/`` package if that file outgrows easy navigation — not preemptively.

``allchats_sdk.types`` is an **internal** package of media/voice helpers for
providers; prefer importing concrete submodules (e.g. ``types.media``).

## Quick start

```python
from allchats_sdk import FileCredentialStore, TelegramClient

store = FileCredentialStore("./telegram-session.json")
client = TelegramClient(
    account_id=account_id,
    app_id=12345,
    app_hash="your_app_hash",
    credential_store=store,
)
await client.auth.start_qr()
status = await client.auth.wait_until_authorized()
await client.connect()
message_id, chat_id = await client.messages.send("hello", chat_id="123")
```

## Examples

Examples are the main guide to the public API. See [`examples/README.md`](examples/README.md).

```bash
cd allchats-sdk
pip install -e ".[telegram,vk]"

# Telegram
export TELEGRAM_APP_ID=… TELEGRAM_APP_HASH=…
python examples/telegram/connect_qr.py
python examples/telegram/reconnect.py
export TELEGRAM_CHAT_ID=… && python examples/telegram/send_message.py "hi"
python examples/telegram/receive_messages.py

# VK
python examples/vk/connect_qr.py
export VK_ACCESS_TOKEN=… && python examples/vk/connect_token.py
export VK_CHAT_ID=… && python examples/vk/send_message.py "hi"
```

Typical Telegram shape (what the examples teach):

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
await client.auth.start_qr()
await client.auth.wait_until_authorized(
    password_provider=lambda: input("2FA password: "),
)
await client.connect()
await client.messages.send("hello", chat_id="123")
```

MAX needs a host ``SessionManager`` as ``session_host`` — see ``examples/max/``.

## Providers

| Provider | Extra | Auth | Registry |
|----------|-------|------|----------|
| Telegram | `[telegram]` | QR, 2FA | yes |
| VK | `[vk]` | OAuth, QR, login | yes |
| MAX | `[max]` | QR, SMS | host SessionManager |
| Avito | `[avito]` | OAuth | yes |
| WhatsApp | `[whatsapp]` | QR (neonize) | yes |
| Discord | `[discord]` | QR, login | yes |

Shared package layout for first-class providers:

```text
providers/<name>/
  provider.py   # TelegramProvider / VKProvider / MAXProvider
  client.py     # transport / account state (not allchats_sdk.clients.*)
  auth.py       # auth flows
  manager.py    # BC shim (telegram/vk)
```

Shared conceptual methods: ``connect_account``, ``start_qr``, ``disconnect``,
``send_message``, ``client_for_account``.

Register built-in providers once at startup (host / advanced):

```python
from allchats_sdk.internal.registry import default_registry
from allchats_sdk.internal.runtime.register import register_builtin_providers

register_builtin_providers()  # mutates default_registry
```

Telegram helpers:

- ``allchats_sdk.providers.telegram.contacts`` — contact search
- ``allchats_sdk.providers.telegram.peers`` — peer ID resolution
- ``allchats_sdk.providers.telegram.health`` — connectivity ping

VK helpers:

- ``allchats_sdk.providers.vk.wall`` — ``resolve_group`` / ``resolve_group_async``, ``iter_wall_posts`` / ``iter_wall_posts_sync``
- ``allchats_sdk.providers.vk.catalog`` — ``get_search_statuses`` (wall posts via ``catalog.getSearchStatuses``), ``get_search_top`` (search UI people/groups)
- ``allchats_sdk.providers.vk.native_api.vk_method`` — low-level VK RPC with ``error_code`` and rate-limit retries (codes 6 / 29); pass ``v=`` to override API version

MAX helpers:

- ``allchats_sdk.providers.max.users`` — ``max_user_display_name``, ``resolve_max_user_display_name(s)``

## Credentials

Canonical credential helpers live in ``allchats_sdk.credentials``:

```python
from allchats_sdk.credentials import (
    is_authorized,
    merge_credentials,
    sanitize_credentials,
    telegram_authorized,
    vk_authorized,
    new_telegram_credentials,
)

creds = new_telegram_credentials(account_id="acc-1")
if telegram_authorized(creds):
    ...

safe = sanitize_credentials(creds)  # masks tokens/session_data for logs/API
merged = merge_credentials(existing, incoming)
```

Supported authorization checks: ``telegram``, ``vk``, ``whatsapp``, ``discord``, ``avito``, ``native`` (MAX).

## Incoming pipeline

Providers emit lightweight events via ``EventSink``. Rich media (voice, photos, etc.)
is processed by the host ``IncomingMessageHandler`` (e.g. ``VoiceMessageService``),
which downloads media, persists messages, and publishes ``MessageReceived`` /
``FileReceived`` to the application Event Bus.

## Protocols

Host/backend implements SDK protocols from ``allchats_sdk.protocols``:

| Protocol | Role |
|----------|------|
| ``EventSink`` | receive provider events (messages, auth, chat sync) |
| ``MediaStorage`` | persist downloaded voice/media/avatar files |
| ``DeliveryTracker`` | delivery/read receipt tracking |
| ``IncomingMessageHandler`` | rich media incoming/outgoing processing |
| ``CredentialStorage`` | optional persistent credentials (for MessengerClient) |
| ``MaxSessionHost`` / ``SessionManager`` | MAX session orchestration (host-owned) |

``NullEventSink`` is a no-op implementation for tests and standalone scripts.

Legacy shims (same symbols): ``allchats_sdk.host_ports``, ``allchats_sdk.host``
(prefer ``allchats_sdk.protocols`` / ``allchats_sdk.internal.runtime``).

## Events

Providers emit events through ``EventSink``:

| Event | Purpose |
|-------|---------|
| ``IncomingMessageEvent`` | inbound message (+ ``metadata`` for media fields) |
| ``OutgoingMessageEvent`` | outbound message |
| ``CredentialsUpdatedEvent`` | persist or clear session credentials |
| ``ConnectionStateEvent`` | auth/runtime state changes |
| ``ChatsDiscoveredEvent`` | initial chat/channel sync |
| ``ChatIdRemapEvent`` | e.g. WhatsApp LID↔PN remaps |

Media metadata keys commonly passed via ``IncomingMessageEvent.metadata``:

``message_type``, ``media_path``, ``duration_ms``, ``media_filename``, ``grouped_id``, ``from_name``, ``avatar_url``.

## MessengerClient facade

Capability-based per-account API:

- ``TelegramClient`` / ``VKClient`` / ``MAXClient`` — preferred account entrypoints
- ``TelegramProvider`` / ``VKProvider`` / ``MAXProvider`` — typed providers (advanced)
- ``MessengerClient(provider=..., account_id=...)`` — generic facade over a provider
- ``client.messages`` / ``client.chats`` / ``client.auth`` — capabilities
- ``client.connect()`` / ``client.disconnect()`` — session lifecycle

Unsupported capabilities raise ``UnsupportedCapabilityError``.

## Errors

| Exception | When |
|-----------|------|
| ``AllChatsError`` | base public exception (alias: ``MessengerError``) |
| ``ValidationError`` | invalid input / missing config |
| ``MessengerClientUnavailableError`` | provider client not ready |
| ``SessionNotConnectedError`` | MAX/session not connected |
| ``UnsupportedCapabilityError`` | facade capability not supported |

Specific error classes live under ``allchats_sdk.errors`` (internal import path for hosts). Catch ``AllChatsError`` at application boundaries.

``is_telegram_rpc_error(exc)`` detects Telethon ``RPCError`` when ``[telegram]`` extra is installed.

## Development

```bash
cd allchats-sdk
pip install -e ".[all,dev]"
python -m build

# run tests (pytest or unittest)
pytest
python -m unittest discover -s tests -p 'test_*.py' -v
```

Test layout:

```text
tests/
├── unit/           # credentials, events, registry, public root API, …
├── providers/      # telegram / vk / max public clients + provider helpers
└── integration/    # installed-package import paths
```

Prefer public entrypoints in tests (``from allchats_sdk.telegram import TelegramClient``),
not only internal classes.

## Versioning

SemVer. Current version: **0.1.0**.

## Migration from `messenger-sdk`

```python
# old (deprecated)
from messenger_sdk.events import IncomingMessageEvent

# new
from allchats_sdk.events import IncomingMessageEvent
```

The `messenger_sdk` namespace remains as a compatibility shim in `backend/packages/messenger-sdk` (top-level exports only).

## Monorepo / CI

Docker builds expect this layout at the build context root:

```text
.
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt   # -e ../allchats-sdk[all]
│   └── internal/
└── allchats-sdk/
```

- **allchats-infra** local compose: `context: ..`, `dockerfile: backend/Dockerfile`
- **backend** CI: checks out `backend/` and `allchats-sdk/` into the same workspace root
- **backend** `docker-compose.yml`: `context: ..` (sibling `allchats-sdk` required)
