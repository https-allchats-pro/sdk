# Discord

**Status: manager / host integration.** No public `DiscordClient` facade yet.

## Installation

```bash
pip install "allchats-sdk[discord]"
```

## Authentication

`DiscordClientManager` supports QR and login auth workers, `connect_account`,
`send_message`, and EventSink incoming via `selfcord_runtime`.

## Supported capabilities

| Capability | Status |
|------------|--------|
| Public account client | ❌ |
| Manager auth / send / receive | ✅ |
| Media | ⚠️ voice-focused helpers; no general `media.py` |
| Builtin registry | ✅ |

## Limitations

- Heavy optional dependencies (`discord.py-self`, audio stack, …).
- No first-class end-user examples yet.

## Known issues

- Treat as advanced until a public client lands.
