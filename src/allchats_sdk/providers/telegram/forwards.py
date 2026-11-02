from __future__ import annotations

from typing import Any


def extract_telegram_forward_meta(message: Any) -> dict[str, Any] | None:
    """Build forward metadata from a Telethon Message (fwd_from header)."""
    fwd = getattr(message, "fwd_from", None)
    if fwd is None:
        return None

    from_name = str(getattr(fwd, "from_name", "") or "").strip()
    post_author = str(getattr(fwd, "post_author", "") or "").strip()
    channel_post = getattr(fwd, "channel_post", None)

    payload: dict[str, Any] = {"is_forwarded": True}
    label = from_name or post_author
    if label:
        payload["from_name"] = label
    if channel_post is not None:
        payload["from_channel"] = True

    saved_from_peer = getattr(fwd, "saved_from_peer", None)
    if saved_from_peer is not None:
        from telethon import utils

        try:
            payload["saved_from_peer_id"] = str(utils.get_peer_id(saved_from_peer))
        except (TypeError, ValueError):
            pass

    return payload
