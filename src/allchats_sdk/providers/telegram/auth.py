"""Telegram auth flows (QR / 2FA password)."""

from __future__ import annotations

from allchats_sdk.providers.telegram.qr_worker import (
    run_telegram_qr_worker,
    telegram_connect_timeout,
    telegram_qr_wait_timeout,
)

__all__ = [
    "run_telegram_qr_worker",
    "telegram_connect_timeout",
    "telegram_qr_wait_timeout",
]
