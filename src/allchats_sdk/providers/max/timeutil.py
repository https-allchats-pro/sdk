from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _normalize_sent_at_ms(value: int) -> int:
    if value < 10_000_000_000:
        return value * 1000
    return value


def message_sent_at(message: Any) -> datetime:
    raw_time = int(getattr(message, "time", 0) or 0)
    if raw_time:
        return datetime.fromtimestamp(_normalize_sent_at_ms(raw_time) / 1000, tz=UTC)
    return datetime.now(UTC)
