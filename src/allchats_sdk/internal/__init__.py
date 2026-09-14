"""SDK-private modules — not part of the guaranteed public API.

Prefer package-root imports for app code (``TelegramClient``, ``Message``, …).
Import from ``allchats_sdk.internal`` only when you are extending the SDK itself
or wiring the host (backend).
"""

from __future__ import annotations

__all__: list[str] = []
