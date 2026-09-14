# Examples

These scripts are the fastest way to learn the public SDK API.

Prefer:

```python
from allchats_sdk.telegram import TelegramClient
from allchats_sdk import FileCredentialStore
```

## Telegram

```bash
pip install -e ".[telegram]"
export TELEGRAM_APP_ID=… TELEGRAM_APP_HASH=…
```

| Script | What it does |
|--------|----------------|
| [`telegram/connect_qr.py`](telegram/connect_qr.py) | QR login + optional 2FA, saves session |
| [`telegram/reconnect.py`](telegram/reconnect.py) | Connect from saved session file |
| [`telegram/send_message.py`](telegram/send_message.py) | Send text (`TELEGRAM_CHAT_ID`) |
| [`telegram/receive_messages.py`](telegram/receive_messages.py) | Print incoming messages |

## VK

```bash
pip install -e ".[vk]"
```

| Script | What it does |
|--------|----------------|
| [`vk/connect_qr.py`](vk/connect_qr.py) | QR login |
| [`vk/connect_token.py`](vk/connect_token.py) | User access token |
| [`vk/connect_oauth.py`](vk/connect_oauth.py) | VK ID OAuth (PKCE) |
| [`vk/reconnect.py`](vk/reconnect.py) | Connect from saved session |
| [`vk/send_message.py`](vk/send_message.py) | Send text (`VK_CHAT_ID`) |
| [`vk/receive_messages.py`](vk/receive_messages.py) | Print incoming (longpoll) |

## MAX

MAX sessions are owned by the host (`SessionManager`). Wire `get_session_host()` in:

| Script | What it shows |
|--------|----------------|
| [`max/connect.py`](max/connect.py) | `MAXClient` + `connect()` |
| [`max/connect_qr.py`](max/connect_qr.py) | `auth.start_qr(credentials)` |
| [`max/send_message.py`](max/send_message.py) | `messages.send(...)` |

## Host (advanced)

| Script | What it shows |
|--------|----------------|
| [`host/event_bus.py`](host/event_bus.py) | Public `Message` → in-memory bus → feature handler |

## Tips

- Session files default to `./telegram-session.json` / `./vk-session.json` (override with `*_SESSION_FILE`).
- Keep secrets in env vars; do not commit session JSON.
- Account clients persist credentials automatically when you pass `credential_store=`.
