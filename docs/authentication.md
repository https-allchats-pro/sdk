# Authentication

## Telegram

```python
from allchats_sdk.telegram import TelegramClient
from allchats_sdk import FileCredentialStore

client = TelegramClient(
    account_id="acc-1",
    app_id=12345,
    app_hash="…",
    credential_store=FileCredentialStore("./telegram-session.json"),
)

await client.auth.start_qr()
status = await client.auth.wait_until_authorized(
    password_provider=lambda: input("2FA password: "),
)
# later
await client.connect()
```

Methods used via `client.auth`: `start_qr`, `wait_until_authorized`, `submit_password`, `connect`, `disconnect`, `get_state`.

## VK

```python
from allchats_sdk.vk import VKClient

client = VKClient(account_id="acc-1", app_id="…", credential_store=store)

await client.auth.start_qr()
# or
await client.auth.connect_with_token(access_token)
# or
url = client.auth.build_oauth_url()
await client.auth.connect_with_oauth_code(code=…, oauth_state=…, device_id=…)

await client.auth.wait_until_authorized()
await client.connect()
```

## MAX

Requires a host `SessionManager` (or compatible object) as `session_host`:

```python
from allchats_sdk.max import MAXClient

client = MAXClient(account_id="acc-1", session_host=session_manager)
await client.connect()
await client.auth.start_qr(credentials)
```

Standalone QR without a host is not supported.

## WhatsApp / Discord / Avito

Implemented as provider managers (registry / host wiring). There is no
`WhatsAppClient` / `DiscordClient` / `AvitoClient` public facade yet. Use the
managers from `allchats_sdk.providers.*` only if you are extending the SDK or
wiring a host — not as the preferred public API.
