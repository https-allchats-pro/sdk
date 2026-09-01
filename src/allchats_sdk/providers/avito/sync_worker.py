from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from allchats_sdk.events import (
    ChatsDiscoveredEvent,
    IncomingMessageEvent,
    OutgoingMessageEvent,
)
from allchats_sdk.providers.avito.client import (
    AvitoApiError,
    chat_avatar_from_api,
    chat_listing_from_api,
    chat_title_from_api,
    enrich_listing_city,
    extract_message_text,
    get_chat_messages,
    list_chats,
    message_sent_at,
)
from allchats_sdk.providers.avito.media import (
    AVITO_VOICE_DEFAULT_EXTENSION,
    avito_media_fields,
    download_avito_url,
    extract_avito_image_url,
    extract_avito_voice_id,
    get_avito_voice_files,
    guess_extension_from_url,
)
from allchats_sdk.credentials import avito_sync_started_at_ms
from allchats_sdk.types.voice import MESSAGE_TYPE_VOICE

if TYPE_CHECKING:
    from allchats_sdk.providers.avito.manager import AvitoClientManager
    from allchats_sdk.protocols import EventSink

logger = logging.getLogger(__name__)

CHATS_PAGE_SIZE = 50
MESSAGES_BACKFILL_LIMIT = 40


async def run_avito_sync_worker(
    account_id: str,
    *,
    manager: AvitoClientManager,
    event_sink: EventSink,
    poll_interval_sec: float,
    stop_event: asyncio.Event,
) -> None:
    seen_message_ids: set[str] = set()
    bootstrapped = False

    logger.info("starting avito native sync account=%s", account_id[:8])

    while not stop_event.is_set():
        try:
            credentials = await manager.get_sync_credentials(account_id)
            user_id = str(credentials.get("user_id") or "").strip()
            access_token = str(credentials.get("access_token") or "").strip()
            if not user_id or not access_token:
                break

            proxies = manager.requests_proxies(credentials)
            sync_started_at_ms = avito_sync_started_at_ms(credentials)
            offset = 0
            while not stop_event.is_set():
                payload = await list_chats(
                    user_id=user_id,
                    access_token=access_token,
                    limit=CHATS_PAGE_SIZE,
                    offset=offset,
                    proxies=proxies,
                )
                chats = payload.get("chats") or []
                if not isinstance(chats, list) or not chats:
                    break

                for chat in chats:
                    if stop_event.is_set():
                        break
                    if not isinstance(chat, dict):
                        continue
                    await _sync_chat(
                        account_id,
                        chat=chat,
                        user_id=user_id,
                        access_token=access_token,
                        event_sink=event_sink,
                        seen_message_ids=seen_message_ids,
                        bootstrapped=bootstrapped,
                        sync_started_at_ms=sync_started_at_ms,
                        proxies=proxies,
                        manager=manager,
                    )

                if len(chats) < CHATS_PAGE_SIZE:
                    break
                offset += CHATS_PAGE_SIZE

            bootstrapped = True
        except asyncio.CancelledError:
            raise
        except AvitoApiError as exc:
            if exc.status == 402:
                logger.warning(
                    "avito messenger subscription required account=%s",
                    account_id[:8],
                )
            else:
                logger.warning(
                    "avito sync failed account=%s: %s",
                    account_id[:8],
                    exc,
                )
        except Exception:
            logger.exception("avito sync failed account=%s", account_id[:8])

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(5.0, poll_interval_sec))
            break
        except asyncio.TimeoutError:
            continue

    logger.info("stopped avito native sync account=%s", account_id[:8])


async def _sync_chat(
    account_id: str,
    *,
    chat: dict[str, Any],
    user_id: str,
    access_token: str,
    event_sink: EventSink,
    seen_message_ids: set[str],
    bootstrapped: bool,
    sync_started_at_ms: int | None,
    proxies: dict[str, str] | None = None,
    manager: AvitoClientManager,
) -> None:
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return

    title = chat_title_from_api(chat, owner_user_id=user_id)
    avatar_url = chat_avatar_from_api(chat, owner_user_id=user_id)
    listing = chat_listing_from_api(chat)
    if listing:
        listing = await enrich_listing_city(
            listing,
            user_id=user_id,
            access_token=access_token,
            proxies=proxies,
        )

    chat_payload: dict[str, Any] = {
        "external_chat_id": chat_id,
        "title": title,
    }
    if avatar_url:
        chat_payload["avatar_url"] = avatar_url
    if listing:
        chat_payload["listing"] = listing

    await event_sink.on_chats_discovered(
        ChatsDiscoveredEvent(
            connection_id=account_id,
            provider="avito",
            chats=[chat_payload],
        )
    )

    if not bootstrapped:
        messages = await get_chat_messages(
            user_id=user_id,
            chat_id=chat_id,
            access_token=access_token,
            limit=MESSAGES_BACKFILL_LIMIT,
            proxies=proxies,
        )
        for message in messages:
            message_id = str(message.get("id") or "").strip()
            if message_id:
                seen_message_ids.add(message_id)
        return

    last_message = chat.get("last_message")
    if not isinstance(last_message, dict):
        return

    message_id = str(last_message.get("id") or "").strip()
    if not message_id or message_id in seen_message_ids:
        return

    direction = _message_direction(last_message, owner_user_id=user_id)
    if direction == "in":
        await _handle_message(
            account_id,
            chat_id=chat_id,
            title=title,
            owner_user_id=user_id,
            message=last_message,
            event_sink=event_sink,
            seen_message_ids=seen_message_ids,
            sync_started_at_ms=sync_started_at_ms,
            manager=manager,
            access_token=access_token,
            proxies=proxies,
        )
        return
    if direction == "out":
        await _handle_outgoing_message(
            account_id,
            chat_id=chat_id,
            title=title,
            owner_user_id=user_id,
            message=last_message,
            event_sink=event_sink,
            seen_message_ids=seen_message_ids,
            sync_started_at_ms=sync_started_at_ms,
            manager=manager,
            access_token=access_token,
            proxies=proxies,
        )

    messages = await get_chat_messages(
        user_id=user_id,
        chat_id=chat_id,
        access_token=access_token,
        limit=20,
        proxies=proxies,
    )
    for message in messages:
        msg_id = str(message.get("id") or "").strip()
        if not msg_id or msg_id in seen_message_ids:
            continue
        msg_direction = _message_direction(message, owner_user_id=user_id)
        if msg_direction == "in":
            await _handle_message(
                account_id,
                chat_id=chat_id,
                title=title,
                owner_user_id=user_id,
                message=message,
                event_sink=event_sink,
                seen_message_ids=seen_message_ids,
                sync_started_at_ms=sync_started_at_ms,
                manager=manager,
                access_token=access_token,
                proxies=proxies,
            )
        elif msg_direction == "out":
            await _handle_outgoing_message(
                account_id,
                chat_id=chat_id,
                title=title,
                owner_user_id=user_id,
                message=message,
                event_sink=event_sink,
                seen_message_ids=seen_message_ids,
                sync_started_at_ms=sync_started_at_ms,
                manager=manager,
                access_token=access_token,
                proxies=proxies,
            )
        else:
            seen_message_ids.add(msg_id)


async def _persist_incoming_message(
    account_id: str,
    *,
    chat_id: str,
    title: str,
    owner_user_id: str,
    message: dict[str, Any],
    event_sink: EventSink,
    manager: AvitoClientManager,
    access_token: str,
    proxies: dict[str, str] | None,
) -> None:
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return

    author_id = str(message.get("author_id") or "").strip() or chat_id
    timestamp = message_sent_at(message)
    if timestamp is None:
        sent_at = datetime.now(UTC)
    else:
        sent_at = datetime.fromtimestamp(timestamp, tz=UTC)

    text = extract_message_text(message)
    message_type = "text"
    media_path: str | None = None
    duration_ms: int | None = None

    fields = avito_media_fields(message)
    media_storage = getattr(manager, "_media_storage", None)
    if fields is not None:
        message_type = str(fields["message_type"])
        text = str(fields["text"])
        if media_storage is not None:
            try:
                if fields["kind"] == "image":
                    url = extract_avito_image_url(message)
                    if url:
                        data = await asyncio.to_thread(download_avito_url, url, proxies=proxies)
                        extension = guess_extension_from_url(url, default=".jpg")
                        media_path = media_storage.save_media(
                            account_id=account_id,
                            data=data,
                            extension=extension,
                        )
                elif fields["kind"] == "voice":
                    voice_id = extract_avito_voice_id(message)
                    if voice_id:
                        voices = await get_avito_voice_files(
                            user_id=owner_user_id,
                            access_token=access_token,
                            voice_ids=[voice_id],
                            proxies=proxies,
                        )
                        url = voices.get(voice_id)
                        if url:
                            data = await asyncio.to_thread(download_avito_url, url, proxies=proxies)
                            extension = guess_extension_from_url(
                                url,
                                default=AVITO_VOICE_DEFAULT_EXTENSION,
                            )
                            media_path = media_storage.save_voice(
                                account_id=account_id,
                                data=data,
                                extension=extension,
                            )
                            message_type = MESSAGE_TYPE_VOICE
            except Exception:
                logger.exception(
                    "failed to download avito media account=%s chat=%s msg=%s",
                    account_id[:8],
                    chat_id,
                    message_id,
                )

    if not text:
        return

    metadata: dict[str, Any] = {"message_type": message_type}
    if media_path:
        metadata["media_path"] = media_path
    if duration_ms is not None:
        metadata["duration_ms"] = duration_ms

    await event_sink.on_incoming(
        IncomingMessageEvent(
            connection_id=account_id,
            provider="avito",
            external_chat_id=chat_id,
            external_message_id=message_id,
            from_id=author_id,
            text=text,
            sent_at=sent_at,
            title=title,
            metadata=metadata,
        )
    )


async def _handle_outgoing_message(
    account_id: str,
    *,
    chat_id: str,
    title: str,
    owner_user_id: str,
    message: dict[str, Any],
    event_sink: EventSink,
    seen_message_ids: set[str],
    sync_started_at_ms: int | None,
    manager: AvitoClientManager,
    access_token: str,
    proxies: dict[str, str] | None,
) -> None:
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return

    seen_message_ids.add(message_id)

    if not _is_outgoing_message(message, owner_user_id):
        return

    if _message_sent_before_sync(message, sync_started_at_ms):
        return

    await _persist_outgoing_message(
        account_id,
        chat_id=chat_id,
        title=title,
        owner_user_id=owner_user_id,
        message=message,
        event_sink=event_sink,
        manager=manager,
        access_token=access_token,
        proxies=proxies,
    )


async def _persist_outgoing_message(
    account_id: str,
    *,
    chat_id: str,
    title: str,
    owner_user_id: str,
    message: dict[str, Any],
    event_sink: EventSink,
    manager: AvitoClientManager,
    access_token: str,
    proxies: dict[str, str] | None,
) -> None:
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return

    timestamp = message_sent_at(message)
    if timestamp is None:
        sent_at = datetime.now(UTC)
    else:
        sent_at = datetime.fromtimestamp(timestamp, tz=UTC)

    text = extract_message_text(message)
    message_type = "text"
    media_path: str | None = None
    duration_ms: int | None = None

    fields = avito_media_fields(message)
    media_storage = getattr(manager, "_media_storage", None)
    if fields is not None:
        message_type = str(fields["message_type"])
        text = str(fields["text"])
        if media_storage is not None:
            try:
                if fields["kind"] == "image":
                    url = extract_avito_image_url(message)
                    if url:
                        data = await asyncio.to_thread(download_avito_url, url, proxies=proxies)
                        extension = guess_extension_from_url(url, default=".jpg")
                        media_path = media_storage.save_media(
                            account_id=account_id,
                            data=data,
                            extension=extension,
                        )
                elif fields["kind"] == "voice":
                    voice_id = extract_avito_voice_id(message)
                    if voice_id:
                        voices = await get_avito_voice_files(
                            user_id=owner_user_id,
                            access_token=access_token,
                            voice_ids=[voice_id],
                            proxies=proxies,
                        )
                        url = voices.get(voice_id)
                        if url:
                            data = await asyncio.to_thread(download_avito_url, url, proxies=proxies)
                            extension = guess_extension_from_url(
                                url,
                                default=AVITO_VOICE_DEFAULT_EXTENSION,
                            )
                            media_path = media_storage.save_voice(
                                account_id=account_id,
                                data=data,
                                extension=extension,
                            )
                            message_type = MESSAGE_TYPE_VOICE
            except Exception:
                logger.exception(
                    "failed to download avito outgoing media account=%s chat=%s msg=%s",
                    account_id[:8],
                    chat_id,
                    message_id,
                )

    if not text:
        return

    metadata: dict[str, Any] = {"message_type": message_type}
    if media_path:
        metadata["media_path"] = media_path
    if duration_ms is not None:
        metadata["duration_ms"] = duration_ms

    await event_sink.on_outgoing(
        OutgoingMessageEvent(
            connection_id=account_id,
            provider="avito",
            external_chat_id=chat_id,
            external_message_id=message_id,
            from_id=owner_user_id,
            text=text,
            sent_at=sent_at,
            title=title,
            metadata=metadata,
        )
    )


async def _handle_message(
    account_id: str,
    *,
    chat_id: str,
    title: str,
    owner_user_id: str,
    message: dict[str, Any],
    event_sink: EventSink,
    seen_message_ids: set[str],
    sync_started_at_ms: int | None,
    manager: AvitoClientManager,
    access_token: str,
    proxies: dict[str, str] | None,
) -> None:
    message_id = str(message.get("id") or "").strip()
    if not message_id:
        return

    seen_message_ids.add(message_id)

    direction = str(message.get("direction") or "").strip().lower()
    if direction != "in":
        return

    if _message_sent_before_sync(message, sync_started_at_ms):
        return

    await _persist_incoming_message(
        account_id,
        chat_id=chat_id,
        title=title,
        owner_user_id=owner_user_id,
        message=message,
        event_sink=event_sink,
        manager=manager,
        access_token=access_token,
        proxies=proxies,
    )


async def handle_avito_webhook_payload(
    account_id: str,
    payload: dict[str, Any],
    *,
    manager: AvitoClientManager,
    event_sink: EventSink,
) -> None:
    message = _extract_webhook_message(payload)
    if message is None:
        return

    credentials = await manager.get_sync_credentials(account_id)
    user_id = str(credentials.get("user_id") or "").strip()
    sync_started_at_ms = avito_sync_started_at_ms(credentials)
    chat_id = str(message.get("chat_id") or "").strip()
    if not chat_id:
        return

    title = chat_id
    proxies = manager.requests_proxies(credentials)
    try:
        from allchats_sdk.providers.avito.client import chat_listing_from_api, list_chats

        chats_payload = await list_chats(
            user_id=user_id,
            access_token=str(credentials.get("access_token") or ""),
            limit=CHATS_PAGE_SIZE,
            proxies=proxies,
        )
        for chat in chats_payload.get("chats") or []:
            if isinstance(chat, dict) and str(chat.get("id") or "") == chat_id:
                title = chat_title_from_api(chat, owner_user_id=user_id)
                avatar_url = chat_avatar_from_api(chat, owner_user_id=user_id)
                listing = chat_listing_from_api(chat)
                if listing:
                    listing = await enrich_listing_city(
                        listing,
                        user_id=user_id,
                        access_token=str(credentials.get("access_token") or ""),
                        proxies=proxies,
                    )
                chat_payload: dict[str, Any] = {
                    "external_chat_id": chat_id,
                    "title": title,
                }
                if avatar_url:
                    chat_payload["avatar_url"] = avatar_url
                if listing:
                    chat_payload["listing"] = listing
                await event_sink.on_chats_discovered(
                    ChatsDiscoveredEvent(
                        connection_id=account_id,
                        provider="avito",
                        chats=[chat_payload],
                    )
                )
                break
    except Exception:
        logger.debug("avito webhook chat title lookup failed", exc_info=True)

    direction = str(message.get("direction") or "").strip().lower()
    author_id = str(message.get("author_id") or "").strip()
    # Never default missing direction to "in" — that marks our own sends as incoming.
    if direction == "out" or (
        direction != "in"
        and author_id
        and user_id
        and author_id == str(user_id).strip()
    ):
        if _message_sent_before_sync(message, sync_started_at_ms):
            return
        access_token = str(credentials.get("access_token") or "").strip()
        await _persist_outgoing_message(
            account_id,
            chat_id=chat_id,
            title=title,
            owner_user_id=user_id,
            message=message,
            event_sink=event_sink,
            manager=manager,
            access_token=access_token,
            proxies=proxies,
        )
        return
    if direction != "in":
        if not author_id or not user_id or author_id == str(user_id).strip():
            return

    if _message_sent_before_sync(message, sync_started_at_ms):
        return

    access_token = str(credentials.get("access_token") or "").strip()
    await _persist_incoming_message(
        account_id,
        chat_id=chat_id,
        title=title,
        owner_user_id=user_id,
        message=message,
        event_sink=event_sink,
        manager=manager,
        access_token=access_token,
        proxies=proxies,
    )


def _extract_webhook_message(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    nested = payload.get("payload")
    if isinstance(nested, dict):
        msg_type = str(nested.get("type") or "").strip().lower()
        value = nested.get("value")
        if msg_type == "message" and isinstance(value, dict):
            return value
        if isinstance(value, dict) and value.get("id"):
            return value

    if payload.get("id") and payload.get("chat_id"):
        return payload

    return None


def _message_direction(message: dict[str, Any], *, owner_user_id: str) -> str | None:
    direction = str(message.get("direction") or "").strip().lower()
    if direction in {"in", "out"}:
        return direction

    author_id = str(message.get("author_id") or "").strip()
    owner = str(owner_user_id or "").strip()
    if author_id and owner:
        if author_id == owner:
            return "out"
        return "in"
    return None


def _is_outgoing_message(message: dict[str, Any], owner_user_id: str) -> bool:
    return _message_direction(message, owner_user_id=owner_user_id) == "out"


def _message_sent_at_ms(message: dict[str, Any]) -> int | None:
    timestamp = message_sent_at(message)
    if timestamp is None or timestamp <= 0:
        return None
    if timestamp < 10_000_000_000:
        return timestamp * 1000
    return timestamp


def _message_sent_before_sync(message: dict[str, Any], sync_started_at_ms: int | None) -> bool:
    if sync_started_at_ms is None or sync_started_at_ms <= 0:
        return False
    message_ms = _message_sent_at_ms(message)
    if message_ms is None:
        return False
    return message_ms < sync_started_at_ms
