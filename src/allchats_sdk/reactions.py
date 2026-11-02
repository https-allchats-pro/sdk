"""Helpers to normalize messenger reaction payloads to emoji -> user id lists."""

from __future__ import annotations

from typing import Any


def reactions_from_max_counters(counters: list[Any]) -> dict[str, list[str]]:
    reactions: dict[str, list[str]] = {}
    for item in counters or []:
        emoji = str(getattr(item, "reaction", None) or (item.get("reaction") if isinstance(item, dict) else "") or "").strip()
        if not emoji:
            continue
        try:
            count = int(getattr(item, "count", None) or (item.get("count") if isinstance(item, dict) else 0) or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            continue
        reactions[emoji] = [f"max:{emoji}:{index}" for index in range(count)]
    return reactions


def parse_whatsapp_reaction_message(message_proto: Any) -> tuple[str, str, bool] | None:
    """Return (target_message_id, emoji, is_remove) for a WA reaction message."""
    from allchats_sdk.providers.whatsapp.client import proto_field_present

    if not proto_field_present(message_proto, "reactionMessage"):
        return None
    reaction = getattr(message_proto, "reactionMessage", None)
    if reaction is None or not getattr(reaction, "key", None):
        return None
    key = reaction.key
    target_id = str(getattr(key, "ID", "") or getattr(key, "id", "") or "").strip()
    if not target_id:
        return None
    emoji = str(getattr(reaction, "text", "") or "").strip()
    return target_id, emoji, not bool(emoji)
