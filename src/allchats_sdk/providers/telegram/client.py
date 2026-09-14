"""Per-account Telegram session state.

Telethon lives on ``TelegramAccountClient.telethon_client``.
Not the public ``allchats_sdk.clients.TelegramClient`` facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["TelegramAccountClient"]


@dataclass
class TelegramAccountClient:
    account_id: str
    state_instance: str = "starting"
    user_id: str = ""
    error: str = ""
    running: bool = False
    qr_link: str = ""
    track_id: str = ""
    polling_interval: int = 3000
    expires_at: int = 0
    password_hint: str = ""
    telethon_client: Any = field(default=None, repr=False, compare=False)
    entities_loaded: bool = False

    @property
    def is_authorized(self) -> bool:
        return self.state_instance == "authorized" or bool(str(self.user_id or "").strip())
