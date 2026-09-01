"""Telegram peer ID helpers (Telethon-backed)."""

from __future__ import annotations

from typing import Any


def get_peer_id(peer: Any) -> int:
    from telethon import utils

    return utils.get_peer_id(peer)
