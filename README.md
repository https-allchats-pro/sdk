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

## Quick start

```python
from allchats_sdk import MessengerClient, NullEventSink, default_registry
from allchats_sdk.providers.register import register_builtin_providers

register_builtin_providers()
manager = default_registry.create(
    "telegram",
    settings=settings,
    event_sink=NullEventSink(),
)

# Per-account facade
client = MessengerClient.from_provider("telegram", account_id, manager)
await client.connect(credentials)
message_id, chat_id = await client.messages.send("hello", chat_id="123")
```

For MAX (host-managed sessions via SessionManager):

```python
from allchats_sdk import MaxMessengerClient

max_client = MaxMessengerClient(account_id, session_host=session_manager)
await max_client.connect()
await max_client.messages.send("hello", chat_id="12345")
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

MAX helpers:

- ``allchats_sdk.providers.max.users`` — user display name resolution

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

Capability-based per-account API over registry providers:

- ``MessengerClient`` — wraps ``ProviderRegistry`` managers (telegram, vk, whatsapp, …)
- ``MaxMessengerClient`` — adapter over host ``SessionManager`` for MAX
- ``client.messages`` — send text messages
- ``client.chats`` — client state / sync (when supported)
- ``client.auth`` — connect, QR, disconnect (when supported)
- ``client.connect()`` / ``client.disconnect()`` — session lifecycle shortcuts

Unsupported capabilities raise ``UnsupportedCapabilityError``.

## Errors

| Exception | When |
|-----------|------|
| ``ValidationError`` | invalid input / missing config |
| ``MessengerClientUnavailableError`` | provider client not ready |
| ``SessionNotConnectedError`` | MAX/session not connected |
| ``UnsupportedCapabilityError`` | facade capability not supported |

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
