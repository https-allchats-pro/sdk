from __future__ import annotations

from typing import Any

from telethon import utils
from telethon.tl.types import ReactionCustomEmoji, ReactionEmoji


def reaction_to_emoji(reaction: Any) -> str:
    if isinstance(reaction, ReactionEmoji):
        return str(reaction.emoticon or "").strip() or "?"
    if isinstance(reaction, ReactionCustomEmoji):
        return f"custom:{reaction.document_id}"
    return "?"


def build_reactions_map(reactions_obj: Any) -> dict[str, list[str]]:
    if reactions_obj is None:
        return {}
    reactions: dict[str, list[str]] = {}
    for peer_reaction in getattr(reactions_obj, "recent_reactions", None) or []:
        emoji = reaction_to_emoji(getattr(peer_reaction, "reaction", None))
        peer = getattr(peer_reaction, "peer_id", None)
        if peer is None:
            continue
        user_id = str(utils.get_peer_id(peer))
        bucket = reactions.setdefault(emoji, [])
        if user_id not in bucket:
            bucket.append(user_id)
    return reactions
