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

Stable imports come from the package root:

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

`MaxMessengerClient` remains as a thin alias around ``MAXProvider``.

**Preferred usage** — typed providers, then a generic client:

```python
telegram = TelegramProvider(settings=settings, event_sink=sink)
client = MessengerClient(provider=telegram, account_id=account_id)
await client.connect(credentials)
```

The **registry** is an internal SDK mechanism for hosts that still resolve providers by name. Application code should not import ``allchats_sdk.registry``.

Treat deeper modules as **internal**:

- `allchats_sdk.registry` / `providers.register` — host wiring
- `allchats_sdk.host` / `protocols` — host ports (`EventSink`, storage, …)
- `allchats_sdk.hooks` — optional host hooks

## Quick start

```python
from allchats_sdk import MessengerClient, TelegramProvider

telegram = TelegramProvider(settings=settings, event_sink=event_sink)
client = MessengerClient(provider=telegram, account_id=account_id)
await client.connect(credentials)
message_id, chat_id = await client.messages.send("hello", chat_id="123")
```

## Examples

Runnable scripts in ``examples/``:

| Script | What it shows |
|--------|----------------|
| ``examples/connect_telegram.py`` | Telegram QR login, 2FA password, reconnect from saved ``session_data`` |
| ``examples/connect_vk.py`` | VK QR / user token / VK ID OAuth (PKCE), reconnect from saved token |
| ``examples/event_bus_host.py`` | Public ``Message`` DTO → in-memory event bus → feature handler |

```bash
cd allchats-sdk
pip install -e ".[telegram,vk]"

# Telegram QR
export TELEGRAM_APP_ID=… TELEGRAM_APP_HASH=…
python examples/connect_telegram.py

# VK QR or token
python examples/connect_vk.py --mode qr
export VK_ACCESS_TOKEN=… && python examples/connect_vk.py --mode token
```

For MAX (host-managed sessions via SessionManager):

```python
from allchats_sdk import MAXProvider, MessengerClient

max_provider = MAXProvider(session_host=session_manager)
client = MessengerClient(provider=max_provider, account_id=account_id)
await client.connect()
await client.messages.send("hello", chat_id="12345")
```

## Providers

| Provider | Extra | Auth | Registry |
|----------|-------|------|----------|
| Telegram | `[telegram]` | QR, 2FA | yes |
| VK | `[vk]` | OAuth, QR, login | yes |
| MAX | `[max]` | QR, SMS | host SessionManager |
| Avito | `[avito]` | OAuth | yes |
| WhatsApp | `[whatsapp]` | QR (neonize) | yes |
| Discord | `[discord]` | QR, login | yes |

Register built-in providers once at startup:

```python
from allchats_sdk.providers.register import register_builtin_providers

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

## Host ports

Host implements SDK protocols (``allchats_sdk.host_ports`` / ``allchats_sdk.protocols``):

| Protocol | Role |
|----------|------|
| ``EventSink`` | receive provider events (messages, auth, chat sync) |
| ``MediaStorage`` | persist downloaded voice/media/avatar files |
| ``DeliveryTracker`` | delivery/read receipt tracking |
| ``IncomingMessageHandler`` | rich media incoming/outgoing processing |
| ``CredentialStorage`` | optional persistent credentials (for MessengerClient) |

``NullEventSink`` is a no-op implementation for tests and standalone scripts.

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

Capability-based per-account API over typed providers:

- ``TelegramProvider`` / ``VKProvider`` / ``MAXProvider`` — construct explicitly
- ``MessengerClient(provider=..., account_id=...)`` — per-account facade
- ``MaxMessengerClient`` — thin alias for ``MAXProvider``
- ``client.messages`` — send text messages
- ``client.chats`` — client state / sync (when supported)
- ``client.auth`` — connect, QR, disconnect (when supported)
- ``client.connect()`` / ``client.disconnect()`` — session lifecycle shortcuts

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

Test coverage:

- ``tests/test_public_api.py`` — package-root public exports
- ``tests/test_registry.py`` — provider registry
- ``tests/test_credentials.py`` — authorization, sanitize, merge
- ``tests/test_events.py`` — event payload shapes
- ``tests/test_protocols.py`` — host ports and capability protocols
- ``tests/test_messenger_client.py`` — MessengerClient / MaxMessengerClient
- ``tests/test_errors.py`` — exception helpers

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
