# Security

## Never commit credentials

Keep secrets out of git. The repository `.gitignore` includes:

```gitignore
.env
.env.*
*-session.json
```

Also avoid committing:

```text
*.session
credentials.json
telegram-session.json
vk-session.json
```

## Credential storage

| Store | Guidance |
|-------|----------|
| `FileCredentialStore` | Local/dev convenience; plaintext JSON on disk |
| `MemoryCredentialStore` | Tests / short-lived processes |
| Custom `CredentialStore` | Preferred in production (encrypt at rest, access control) |

Account clients with `credential_store=` persist sessions on
`CredentialsUpdatedEvent`. Treat those files like passwords.

## Logging / redaction

```python
from allchats_sdk.credentials import sanitize_credentials

logger.info("creds=%s", sanitize_credentials(raw))
```

Sensitive keys are replaced with `***` (tokens, `session_data`, secrets, proxy
passwords, …). Always sanitize before logging credential dicts. The SDK does
**not** automatically sanitize arbitrary log lines from third-party libraries
(Telethon, vk-api, …).

## Reporting vulnerabilities

See [SECURITY.md](../SECURITY.md) — use GitHub private vulnerability reporting
when available. Never paste live tokens or session strings into public issues.
