# Credentials

## CredentialStore

Protocol used by account clients:

```python
class CredentialStore(Protocol):
    async def get(self, account_id: str) -> dict[str, Any] | None: ...
    async def save(self, account_id: str, credentials: dict[str, Any]) -> None: ...
    async def clear(self, account_id: str) -> None: ...
```

Implementations:

| Class | Use |
|-------|-----|
| `FileCredentialStore(path)` | Single JSON file — **local / development** |
| `MemoryCredentialStore()` | Tests / ephemeral processes |
| Custom store | Production — DB, KMS-backed vault, etc. |

```python
from allchats_sdk import FileCredentialStore, MemoryCredentialStore

store = FileCredentialStore("./telegram-session.json")
client = TelegramClient(..., credential_store=store)
```

When a store is passed, the SDK wraps your `event_sink` with persistence on
`CredentialsUpdatedEvent` so QR / token login saves automatically.

`FileCredentialStore` stores secrets on disk in plaintext JSON. Restrict
filesystem permissions and do not commit the file. Prefer a custom store in
production.

## Helpers (`allchats_sdk.credentials`)

```python
from allchats_sdk.credentials import (
    is_authorized,
    sanitize_credentials,
    merge_credentials,
    new_telegram_credentials,
)

safe = sanitize_credentials(creds)  # masks tokens / session_data for logs
```

`sanitize_credentials` redacts keys such as `access_token`, `session_data`,
`auth_token`, `refresh_token`, `client_secret`, `token`, proxy passwords, etc.

Authorization helpers exist for `telegram`, `vk`, `whatsapp`, `discord`,
`avito`, and `native` (MAX).
