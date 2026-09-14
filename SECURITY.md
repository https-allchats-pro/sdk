# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ |

## Reporting a vulnerability

Please use **GitHub private vulnerability reporting** for this repository when available:

https://github.com/https-allchats-pro/sdk/security/advisories/new

If private reporting is not enabled, open a security-focused issue without including secrets, session files, or tokens, and describe how to reproduce the problem privately.

Do **not** post credentials, session strings, or API tokens in public issues or pull requests.

## Credential handling (summary)

- Prefer application-managed storage in production; `FileCredentialStore` is for local/dev use.
- Never commit `*-session.json`, `.env`, or similar files.
- Use `sanitize_credentials()` before logging credential dicts.

Details: [docs/security.md](docs/security.md).
