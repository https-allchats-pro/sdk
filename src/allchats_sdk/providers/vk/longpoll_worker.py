from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from allchats_sdk.events import IncomingMessageEvent, OutgoingMessageEvent
from allchats_sdk.providers.vk.native_api import (
    LONGPOLL_WAIT_SEC,
    NativeLongPoll,
    VkNativeApiError,
    get_user_profiles,
    parse_message_update,
    parse_read_outbox_update,
)

if TYPE_CHECKING:
    from allchats_sdk.protocols import DeliveryTracker, EventSink, IncomingMessageHandler

logger = logging.getLogger(__name__)


async def run_vk_longpoll_worker(
    account_id: str,
    *,
    access_token: str,
    owner_user_id: str,
    event_sink: EventSink,
    incoming_handler: IncomingMessageHandler | None,
    stop_event: asyncio.Event,
    proxies: dict[str, str] | None = None,
    delivery_tracker: DeliveryTracker | None = None,
) -> None:
    logger.info("starting vk native longpoll account=%s user=%s", account_id[:8], owner_user_id)

    longpoll = await asyncio.to_thread(NativeLongPoll, access_token, proxies=proxies)
    profile_cache: dict[int, dict[str, str | None]] = {}

    while not stop_event.is_set():
        try:
            updates = await asyncio.to_thread(longpoll.check, wait=LONGPOLL_WAIT_SEC)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("vk native longpoll check failed account=%s: %s", account_id[:8], exc)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)
                break
            except asyncio.TimeoutError:
                try:
                    longpoll = await asyncio.to_thread(NativeLongPoll, access_token, proxies=proxies)
                except Exception as retry_exc:
                    logger.warning(
                        "vk native longpoll reconnect failed account=%s: %s",
                        account_id[:8],
                        retry_exc,
                    )
                continue

        incoming = [item for item in updates if isinstance(item, list)]
        if not incoming:
            continue

        for update in incoming:
            if stop_event.is_set():
                break
            read_update = parse_read_outbox_update(update)
            if read_update is None:
                continue
            if delivery_tracker is None:
                continue
            try:
                await delivery_tracker.mark_up_to_external_id(
                    account_id,
                    external_chat_id=read_update["external_chat_id"],
                    max_external_id=int(read_update["max_message_id"]),
                    status="read",
                )
            except Exception:
                logger.exception(
                    "failed to apply vk read receipt account=%s chat=%s",
                    account_id[:8],
                    read_update.get("external_chat_id"),
                )

        parsed_messages = []
        for update in incoming:
            if stop_event.is_set():
                break
            message = parse_message_update(update)
            if message is not None:
                parsed_messages.append(message)

        if not parsed_messages:
            continue

        missing_profiles = [
            message["title_peer_id"]
            for message in parsed_messages
            if message["title_peer_id"] not in profile_cache
        ]
        if missing_profiles:
            try:
                fetched = await asyncio.to_thread(
                    get_user_profiles,
                    access_token=access_token,
                    user_ids=missing_profiles,
                    proxies=proxies,
                )
                profile_cache.update(fetched)
            except VkNativeApiError as exc:
                logger.warning(
                    "vk native longpoll users.get failed account=%s: %s",
                    account_id[:8],
                    exc,
                )

        for message in parsed_messages:
            if stop_event.is_set():
                break
            try:
                if message.get("is_outgoing"):
                    await _handle_outgoing_message(
                        account_id,
                        message,
                        event_sink,
                        profile_cache,
                        access_token=access_token,
                        incoming_handler=incoming_handler,
                        owner_user_id=owner_user_id,
                    )
                else:
                    await _handle_incoming_message(
                        account_id,
                        message,
                        event_sink,
                        profile_cache,
                        access_token=access_token,
                        incoming_handler=incoming_handler,
                    )
            except Exception:
                logger.exception(
                    "vk longpoll message handle failed account=%s msg=%s",
                    account_id[:8],
                    message.get("message_id"),
                )

    logger.info("stopped vk native longpoll account=%s", account_id[:8])


async def _handle_incoming_message(
    account_id: str,
    message: dict[str, Any],
    event_sink: EventSink,
    profile_cache: dict[int, dict[str, str | None]],
    *,
    access_token: str,
    incoming_handler: IncomingMessageHandler | None = None,
) -> None:
    peer_id = message["peer_id"]
    from_id = message["from_id"]
    title_peer_id = message.get("title_peer_id", from_id)
    external_chat_id = message.get("external_chat_id") or str(peer_id)
    message_id = str(message["message_id"]).strip()
    if not message_id:
        return

    profile = profile_cache.get(title_peer_id) or {}
    title = str(profile.get("name") or title_peer_id)
    avatar_url = profile.get("avatar_url")
    sent_at = _message_sent_at(message)
    is_group = peer_id > int(2e9)
    from_name = None
    if is_group:
        sender_profile = profile_cache.get(from_id) or {}
        from_name = str(sender_profile.get("name") or "").strip() or None

    if incoming_handler is not None:
        await incoming_handler.process_vk_incoming(
            account_id=account_id,
            access_token=access_token,
            parsed=message,
            title=title,
            is_group=is_group,
            from_id=from_id,
            avatar_url=avatar_url,
            sent_at=sent_at,
            from_name=from_name,
        )
        return

    metadata: dict[str, Any] = {}
    if avatar_url:
        metadata["avatar_url"] = avatar_url
    if from_name:
        metadata["from_name"] = from_name

    await event_sink.on_incoming(
        IncomingMessageEvent(
            connection_id=account_id,
            provider="vk",
            external_chat_id=external_chat_id,
            external_message_id=message_id,
            from_id=str(from_id),
            text=str(message["text"]),
            sent_at=sent_at,
            title=title,
            is_group=is_group,
            metadata=metadata,
        )
    )


def _message_sent_at(message: dict[str, Any]) -> datetime:
    timestamp = message.get("timestamp")
    if isinstance(timestamp, int) and timestamp > 0:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    return datetime.now(UTC)


async def _handle_outgoing_message(
    account_id: str,
    message: dict[str, Any],
    event_sink: EventSink,
    profile_cache: dict[int, dict[str, str | None]],
    *,
    access_token: str,
    incoming_handler: IncomingMessageHandler | None = None,
    owner_user_id: str = "",
) -> None:
    peer_id = message["peer_id"]
    title_peer_id = message.get("title_peer_id", peer_id)
    external_chat_id = message.get("external_chat_id") or str(peer_id)
    message_id = str(message["message_id"]).strip()
    if not message_id:
        return

    profile = profile_cache.get(title_peer_id) or {}
    title = str(profile.get("name") or title_peer_id)
    avatar_url = profile.get("avatar_url")
    sent_at = _message_sent_at(message)
    from_id = str(owner_user_id or message.get("from_id") or account_id)

    if incoming_handler is not None:
        await incoming_handler.process_vk_outgoing(
            account_id=account_id,
            access_token=access_token,
            parsed=message,
            title=title,
            is_group=peer_id > int(2e9),
            from_id=from_id,
            avatar_url=avatar_url,
            sent_at=sent_at,
        )
        return

    text = str(message.get("text") or "")
    if not text.strip():
        return

    metadata: dict[str, Any] = {}
    if avatar_url:
        metadata["avatar_url"] = avatar_url

    await event_sink.on_outgoing(
        OutgoingMessageEvent(
            connection_id=account_id,
            provider="vk",
            external_chat_id=external_chat_id,
            external_message_id=message_id,
            text=text,
            from_id=from_id,
            sent_at=sent_at,
            title=title,
            is_group=peer_id > int(2e9),
            metadata=metadata,
        )
    )
