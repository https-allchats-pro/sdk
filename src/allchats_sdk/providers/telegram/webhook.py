"""Telegram Bot API webhook Update → SDK events."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from allchats_sdk.events import IncomingMessageEvent

if TYPE_CHECKING:
    from allchats_sdk.protocols import EventSink

logger = logging.getLogger(__name__)


def _extract_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("message", "edited_message", "channel_post"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


async def handle_telegram_webhook_payload(
    account_id: str,
    payload: dict[str, Any],
    *,
    event_sink: EventSink,
) -> None:
    message = _extract_message(payload)
    if message is None:
        return
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return
    external_chat_id = str(chat.get("id") or "").strip()
    external_message_id = str(message.get("message_id") or "").strip()
    if not external_chat_id or not external_message_id:
        return
    from_user = message.get("from") if isinstance(message.get("from"), dict) else {}
    from_id = str(from_user.get("id") or external_chat_id)
    text = str(message.get("text") or message.get("caption") or "")
    try:
        sent_at = datetime.fromtimestamp(int(message.get("date") or 0), tz=UTC)
    except (TypeError, ValueError):
        sent_at = datetime.now(UTC)
    title = str(chat.get("title") or chat.get("username") or external_chat_id)
    chat_type = str(chat.get("type") or "")
    is_group = chat_type in {"group", "supergroup", "channel"}
    metadata: dict[str, Any] = {}
    from_name = " ".join(
        part
        for part in (
            str(from_user.get("first_name") or "").strip(),
            str(from_user.get("last_name") or "").strip(),
        )
        if part
    ).strip()
    if from_name:
        metadata["from_name"] = from_name
    await event_sink.on_incoming(
        IncomingMessageEvent(
            connection_id=account_id,
            provider="telegram",
            external_chat_id=external_chat_id,
            external_message_id=external_message_id,
            from_id=from_id,
            text=text,
            sent_at=sent_at,
            title=title,
            is_group=is_group,
            metadata=metadata,
        )
    )
