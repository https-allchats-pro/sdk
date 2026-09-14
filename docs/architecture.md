# Architecture

```text
Application
    ↓
AllChats SDK (public clients / models / stores)
    ↓
Provider (TelegramProvider, VKProvider, MAXProvider, …)
    ↓
Messenger network (Telethon, vk-api, pymax, …)
```

Optional host (e.g. AllChats backend) implements protocols and may own MAX sessions:

```text
Host app
  └── EventSink / MediaStorage / IncomingMessageHandler / SessionManager
        ↔  allchats-sdk providers
```

## Layers

| Layer | Role |
|-------|------|
| Account clients | `TelegramClient`, `VKClient`, `MAXClient` — preferred entry |
| `MessengerClient` | Generic facade over a provider (`messages` / `chats` / `auth`) |
| Providers | Multi-account runtime for one messenger |
| Protocols | Host-facing contracts in `allchats_sdk.protocols` |
| Events | Push payloads via `EventSink` |
| Credential store | Persist session dicts for account clients |
| Internal | Registry, hooks, observability, runtime registration |

## Public API

Stable imports:

```python
from allchats_sdk import (
    TelegramClient,  # also: allchats_sdk.telegram
    FileCredentialStore,
    Message,
    ConnectionState,
    Capability,
    AllChatsError,
)
from allchats_sdk.telegram import TelegramClient, TelegramProvider
from allchats_sdk.vk import VKClient
from allchats_sdk.max import MAXClient
```

Root `__all__` in `allchats_sdk/__init__.py` is the source of truth for package-root exports.

## Internal API

Do **not** depend on these in application code:

- `allchats_sdk.internal.*` — registry, hooks, observability, runtime
- `allchats_sdk.providers.*.manager` — compatibility shims / runtime guts
- `allchats_sdk.host`, `host_ports`, top-level `registry` — legacy shims

They may change without a major version bump.

## Telegram stack (example)

```text
TelegramClient → TelegramProvider → MessengerClient → Telethon
                     ↑
              CredentialStore (+ PersistingEventSink when store is set)
```

## Registry

`allchats_sdk.internal.runtime.register.register_builtin_providers` registers
telegram, vk, whatsapp, discord, and avito on the default registry for legacy
`MessengerClient(provider_id=...)` construction. MAX is **not** registered; it
is host-wired via `session_host`.
