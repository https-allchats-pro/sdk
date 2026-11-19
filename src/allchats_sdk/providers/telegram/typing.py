"""Telegram typing updates (private, basic group, channel/supergroup)."""

from __future__ import annotations

from typing import Any


def describe_telegram_typing(update: Any) -> dict[str, Any] | None:
    """Map a raw typing update to the chat id used for messages.

    Returns None for every other action (recording voice, cancel, etc.).
    """
    from telethon import utils
    from telethon.tl import types
    from telethon.tl.types import (
        SendMessageTextDraftAction,
        SendMessageTypingAction,
        UpdateChannelUserTyping,
        UpdateChatUserTyping,
        UpdateUserTyping,
    )

    # Current Telegram clients report composing as a text draft, not only
    # as SendMessageTypingAction. Voice, upload and cancel stay hidden.
    if not isinstance(
        getattr(update, "action", None),
        (SendMessageTypingAction, SendMessageTextDraftAction),
    ):
        return None

    if isinstance(update, UpdateUserTyping):
        user_id = int(update.user_id)
        if user_id <= 0:
            return None
        return {
            "external_chat_id": str(utils.get_peer_id(types.PeerUser(user_id))),
            "user_id": str(user_id),
            "is_group": False,
        }

    if isinstance(update, UpdateChatUserTyping):
        user_id = _peer_user_id(update.from_id)
        chat_id = int(update.chat_id)
        if not user_id or chat_id <= 0:
            return None
        return {
            "external_chat_id": str(utils.get_peer_id(types.PeerChat(chat_id))),
            "user_id": user_id,
            "is_group": True,
        }

    if isinstance(update, UpdateChannelUserTyping):
        user_id = _peer_user_id(update.from_id)
        channel_id = int(update.channel_id)
        if not user_id or channel_id <= 0:
            return None
        return {
            "external_chat_id": str(utils.get_peer_id(types.PeerChannel(channel_id))),
            "user_id": user_id,
            "is_group": True,
        }

    return None


def _peer_user_id(peer: Any) -> str:
    if peer is None:
        return ""
    if isinstance(peer, int):
        return str(peer) if peer > 0 else ""
    user_id = getattr(peer, "user_id", None)
    if user_id is None:
        return ""
    try:
        parsed = int(user_id)
    except (TypeError, ValueError):
        return ""
    return str(parsed) if parsed > 0 else ""
