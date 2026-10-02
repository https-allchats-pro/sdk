# Changelog

## 0.1.2

### Avito

- Skip chats without a real dialogue (no user messages on either side)
- Treat Avito `item` / `system` stubs as non-dialogue so empty
  "start a conversation" chats are not created
- Soft-delete previously saved empty Avito chat shells on sync

## 0.1.1

### Documentation

- Improved README (value proposition, badges, quick start, docs links)
- Added `docs/` guides: getting started, architecture, authentication, events,
  capabilities (matrix), credentials, errors, security
- Added per-provider docs under `docs/providers/`
- Added `SECURITY.md` and security reporting guidance

### Examples

- Documented example index with install / env requirements
- Added `examples/telegram/inspect_capabilities.py`

### Release

- Added GitHub Actions CI (pytest + build + twine check + wheel smoke)
- Added release workflow using PyPI Trusted Publishing (OIDC)
- Bumped package version to `0.1.1`

## 0.1.0

- Initial public release on PyPI
