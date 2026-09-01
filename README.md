# allchats-sdk

Python SDK for messenger integrations (Telegram, VK, MAX, Avito, Discord, WhatsApp).

Standalone package extracted from the AllChats backend. Does not depend on FastAPI, PostgreSQL, or application domain logic.

## Installation

From monorepo root:

```bash
pip install -e "./allchats-sdk[all]"
```

With specific providers:

```bash
pip install -e "./allchats-sdk[telegram,vk]"
```

## Quick start

```python
from allchats_sdk import default_registry
from allchats_sdk.providers.register import register_builtin_providers
from allchats_sdk.protocols import NullEventSink

register_builtin_providers()
manager = default_registry.create(
    "telegram",
    settings=settings,
    event_sink=NullEventSink(),
)
```

## Providers

| Provider | Extra | Auth |
|----------|-------|------|
| Telegram | `[telegram]` | QR, 2FA |
| VK | `[vk]` | OAuth, QR, login |
| MAX | `[max]` | QR, SMS (via host SessionManager) |
| Avito | `[avito]` | OAuth |
| WhatsApp | `[whatsapp]` | QR (neonize) |
| Discord | `[discord]` | QR, login |

Telegram helpers:

- ``allchats_sdk.providers.telegram.contacts`` — contact search
- ``allchats_sdk.providers.telegram.peers`` — peer ID resolution
- ``allchats_sdk.providers.telegram.health`` — connectivity ping

## Storage interfaces

Host implements SDK protocols (see ``allchats_sdk.host_ports``):

- ``MediaStorage`` — save voice/media/avatar files
- ``DeliveryTracker`` — message delivery/read receipts
- ``IncomingMessageHandler`` — rich media incoming/outgoing processing
- ``CredentialStorage`` — optional persistent credentials (future)

## Events

Providers emit events through `EventSink`:

- `on_incoming` / `on_outgoing` — messages
- `on_credentials_updated` — session persist / clear
- `on_connection_state` — auth/runtime state
- `on_chats_discovered` — initial chat sync
- `on_chat_id_remap` — e.g. WhatsApp LID↔PN

## Development

```bash
cd allchats-sdk
pip install -e ".[all]"
python -m build
pytest tests/
```

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
