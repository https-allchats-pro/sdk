# VK

First-class public client: `VKClient` / `VKProvider`.

## Installation

```bash
pip install "allchats-sdk[vk]"
```

Create an app at https://dev.vk.com/ when using OAuth / login features.

```bash
export VK_APP_ID=…          # optional for QR/token depending on flow
export VK_ACCESS_TOKEN=…    # for token mode
```

## Authentication

```python
from allchats_sdk.vk import VKClient
from allchats_sdk import FileCredentialStore

store = FileCredentialStore("./vk-session.json")
client = VKClient(account_id="acc-1", app_id=os.environ.get("VK_APP_ID", ""), credential_store=store)

await client.auth.start_qr()
# or await client.auth.connect_with_token(token)
# or OAuth: build_oauth_url / connect_with_oauth_code

await client.auth.wait_until_authorized()
```

## Connecting

```python
status = await client.connect()
```

## Sending messages

```python
message_id, chat_id = await client.messages.send("hello", chat_id="123456789")
```

`chat_id` is required (peer id as string).

## Receiving messages

Longpoll worker emits `EventSink.on_incoming`. See
`examples/vk/receive_messages.py`.

## Supported capabilities

| Capability | Status |
|------------|--------|
| Auth QR / token / OAuth / login | ✅ |
| `messages.send` | ✅ |
| Receive via EventSink | ✅ |
| `chats.client_state` | ✅ |
| Media helpers | ✅ |
| Builtin registry | ✅ |

## Limitations

- Constructing `VKClient` loads provider code that needs `requests` / `vk-api`
  (`[vk]` extra) at connect time.
- Wall/catalog helpers under `providers.vk` are advanced APIs.

## Known issues

- None tracked specifically for `0.1.1`.
