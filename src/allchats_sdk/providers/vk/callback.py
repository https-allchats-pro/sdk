"""VK Callback API → SDK events (Groups/community server)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from allchats_sdk.events import IncomingMessageEvent, OutgoingMessageEvent
from allchats_sdk.providers.vk.client import external_chat_id_from_peer
from allchats_sdk.providers.vk.longpoll_worker import (
    _handle_incoming_message,
    _handle_outgoing_message,
    prefetch_vk_message_caches,
)
from allchats_sdk.providers.vk.native_api import is_vk_group_peer
from allchats_sdk.providers.vk.native_api import decode_message_text

if TYPE_CHECKING:
    from allchats_sdk.protocols import EventSink, IncomingMessageHandler

logger = logging.getLogger(__name__)


def parse_vk_callback_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    event_type = str(payload.get("type") or "").strip()
    if event_type != "message_new":
        return None
    obj = payload.get("object")
    if not isinstance(obj, dict):
        return None
    message = obj.get("message")
    if not isinstance(message, dict):
        message = obj
    try:
        message_id = int(message.get("id"))
        peer_id = int(message.get("peer_id"))
        from_id = int(message.get("from_id") or peer_id)
        timestamp = int(message.get("date") or datetime.now(UTC).timestamp())
    except (TypeError, ValueError):
        return None
    is_outgoing = bool(int(message.get("out") or 0))
    text = decode_message_text(str(message.get("text") or ""))
    if is_outgoing or is_vk_group_peer(peer_id):
        title_peer_id = peer_id
    else:
        title_peer_id = from_id
    return {
        "message_id": str(message_id),
        "peer_id": peer_id,
        "from_id": from_id,
        "title_peer_id": title_peer_id,
        "timestamp": timestamp,
        "text": text,
        "external_chat_id": external_chat_id_from_peer(peer_id),
        "has_voice": False,
        "has_attachments": bool(message.get("attachments")),
        "is_outgoing": is_outgoing,
    }


async def handle_vk_callback_payload(
    account_id: str,
    payload: dict[str, Any],
    *,
    event_sink: EventSink,
    access_token: str = "",
    incoming_handler: IncomingMessageHandler | None = None,
    owner_user_id: str = "",
) -> None:
    parsed = parse_vk_callback_message(payload)
    if parsed is None:
        return
    profile_cache: dict[int, dict[str, str | None]] = {}
    conversation_cache = await prefetch_vk_message_caches(
        [parsed],
        access_token=access_token,
        profile_cache=profile_cache,
    )
    if parsed.get("is_outgoing"):
        await _handle_outgoing_message(
            account_id,
            parsed,
            event_sink,
            profile_cache,
            conversation_cache=conversation_cache,
            access_token=access_token,
            incoming_handler=incoming_handler,
            owner_user_id=owner_user_id,
        )
    else:
        await _handle_incoming_message(
            account_id,
            parsed,
            event_sink,
            profile_cache,
            conversation_cache=conversation_cache,
            access_token=access_token,
            incoming_handler=incoming_handler,
        )


async def handle_vk_callback_payload_events(
    account_id: str,
    payload: dict[str, Any],
    *,
    event_sink: EventSink,
) -> None:
    """Minimal path for webhook worker (no access_token / media enrichment)."""
    parsed = parse_vk_callback_message(payload)
    if parsed is None:
        return
    sent_at = datetime.fromtimestamp(int(parsed["timestamp"]), tz=UTC)
    peer_id = int(parsed["peer_id"])
    is_group = is_vk_group_peer(peer_id)
    metadata: dict[str, Any] = {}
    if parsed.get("is_outgoing"):
        await event_sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="vk",
                external_chat_id=str(parsed["external_chat_id"]),
                external_message_id=str(parsed["message_id"]),
                text=str(parsed["text"]),
                sent_at=sent_at,
                from_id=str(parsed.get("from_id") or account_id),
                title=str(parsed.get("title_peer_id") or parsed["external_chat_id"]),
                is_group=is_group,
                metadata=metadata,
            )
        )
        return
    await event_sink.on_incoming(
        IncomingMessageEvent(
            connection_id=account_id,
            provider="vk",
            external_chat_id=str(parsed["external_chat_id"]),
            external_message_id=str(parsed["message_id"]),
            from_id=str(parsed["from_id"]),
            text=str(parsed["text"]),
            sent_at=sent_at,
            title=str(parsed.get("title_peer_id") or parsed["external_chat_id"]),
            is_group=is_group,
            metadata=metadata,
        )
    )
