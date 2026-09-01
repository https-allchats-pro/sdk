from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from allchats_sdk.providers.telegram.manager import TelegramAccountClient, TelegramClientManager
    from allchats_sdk.config import Settings
    from allchats_sdk.protocols import (
        DeliveryTracker,
        EventSink,
        IncomingMessageHandler,
        MediaStorage,
    )

logger = logging.getLogger(__name__)


def _resolve_sender_id(client_state: TelegramAccountClient, event: Any) -> str:
    sender_id = str(getattr(event, "sender_id", "") or "").strip()
    if sender_id:
        return sender_id
    return str(getattr(client_state, "user_id", "") or "").strip()


async def _resolve_group_sender_name(event: Any, *, is_group: bool, sender_id: str) -> str | None:
    if not is_group or not sender_id:
        return None
    from allchats_sdk.providers.telegram.entities import resolve_sender_display_name

    return await resolve_sender_display_name(event, sender_id)


async def _resolve_incoming_context(
    client: Any,
    event: Any,
    account_id: str,
    *,
    media_storage: MediaStorage | None = None,
) -> dict[str, Any]:
    from telethon import utils

    from allchats_sdk.providers.telegram.entities import describe_entity, entity_avatar_url

    external_chat_id = str(utils.get_peer_id(event.peer_id))
    entity = await client.get_entity(event.peer_id)
    title, is_group = describe_entity(entity, external_id=external_chat_id)
    access_hash = getattr(entity, "access_hash", None)
    avatar_url = await entity_avatar_url(
        client,
        entity,
        account_id=account_id,
        external_chat_id=external_chat_id,
        media_storage=media_storage,
    )
    return {
        "external_chat_id": external_chat_id,
        "title": title,
        "is_group": is_group,
        "access_hash": access_hash,
        "avatar_url": avatar_url,
    }


def _register_message_handlers(
    *,
    client: Any,
    account_id: str,
    client_state: TelegramAccountClient,
    event_sink: EventSink,
    incoming_handler: IncomingMessageHandler | None = None,
    delivery_tracker: DeliveryTracker | None = None,
    media_storage: MediaStorage | None = None,
) -> None:
    from telethon import events, utils

    from allchats_sdk.events import IncomingMessageEvent, OutgoingMessageEvent
    from allchats_sdk.providers.telegram.media import detect_telegram_media_type

    async def _handle_incoming_message(event: Any) -> None:
        external_chat_id = str(utils.get_peer_id(event.peer_id))
        sender_id = _resolve_sender_id(client_state, event)
        message_id = str(getattr(event.message, "id", "") or "")
        sent_at = getattr(event.message, "date", None)
        if not message_id or sent_at is None:
            return

        chat_context = await _resolve_incoming_context(
            client,
            event,
            account_id,
            media_storage=media_storage,
        )

        action = getattr(event.message, "action", None)
        from telethon.tl.types import MessageActionPhoneCall

        if isinstance(action, MessageActionPhoneCall):
            from allchats_sdk.providers.telegram.calls import telegram_call_coordinator

            service = getattr(telegram_call_coordinator, "_call_log_service", None)
            if service is not None:
                await service.record_telegram_service_message(
                    account_id=account_id,
                    external_chat_id=external_chat_id,
                    chat_id=None,
                    peer_title=chat_context.get("title"),
                    action=action,
                    is_outgoing=False,
                    sent_at=sent_at,
                )
            return

        if incoming_handler is not None:
            await incoming_handler.process_telegram_incoming(
                account_id=account_id,
                client=client,
                event=event,
                external_chat_id=external_chat_id,
                sender_id=sender_id,
                sent_at=sent_at,
                external_message_id=message_id,
                title=chat_context["title"],
                is_group=chat_context["is_group"],
                access_hash=chat_context["access_hash"],
                avatar_url=chat_context["avatar_url"],
                from_name=await _resolve_group_sender_name(
                    event,
                    is_group=chat_context["is_group"],
                    sender_id=sender_id,
                ),
            )
            return

        text = str(getattr(event.message, "message", "") or "")
        if (
            not text.strip()
            and not getattr(event.message, "voice", False)
            and detect_telegram_media_type(event.message) is None
        ):
            return

        metadata: dict[str, Any] = {}
        if chat_context.get("access_hash") is not None:
            metadata["access_hash"] = chat_context["access_hash"]
        if chat_context.get("avatar_url"):
            metadata["avatar_url"] = chat_context["avatar_url"]
        from_name = await _resolve_group_sender_name(
            event,
            is_group=chat_context["is_group"],
            sender_id=sender_id,
        )
        if from_name:
            metadata["from_name"] = from_name

        await event_sink.on_incoming(
            IncomingMessageEvent(
                connection_id=account_id,
                provider="telegram",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                from_id=sender_id,
                text=text,
                sent_at=sent_at,
                title=chat_context["title"],
                is_group=chat_context["is_group"],
                metadata=metadata,
            )
        )

    async def _handle_outgoing_message(event: Any) -> None:
        external_chat_id = str(utils.get_peer_id(event.peer_id))
        from_id = _resolve_sender_id(client_state, event)
        if not from_id:
            from_id = account_id
        message_id = str(getattr(event.message, "id", "") or "")
        sent_at = getattr(event.message, "date", None)
        if not message_id or sent_at is None:
            return

        chat_context = await _resolve_incoming_context(
            client,
            event,
            account_id,
            media_storage=media_storage,
        )

        action = getattr(event.message, "action", None)
        from telethon.tl.types import MessageActionPhoneCall

        if isinstance(action, MessageActionPhoneCall):
            from allchats_sdk.providers.telegram.calls import telegram_call_coordinator

            service = getattr(telegram_call_coordinator, "_call_log_service", None)
            if service is not None:
                await service.record_telegram_service_message(
                    account_id=account_id,
                    external_chat_id=external_chat_id,
                    chat_id=None,
                    peer_title=chat_context.get("title"),
                    action=action,
                    is_outgoing=True,
                    sent_at=sent_at,
                )
            return

        if incoming_handler is not None:
            await incoming_handler.process_telegram_outgoing(
                account_id=account_id,
                client=client,
                event=event,
                external_chat_id=external_chat_id,
                from_id=from_id,
                sent_at=sent_at,
                external_message_id=message_id,
                title=chat_context["title"],
                is_group=chat_context["is_group"],
                access_hash=chat_context["access_hash"],
                avatar_url=chat_context["avatar_url"],
            )
            return

        text = str(getattr(event.message, "message", "") or "")
        if (
            not text.strip()
            and not getattr(event.message, "voice", False)
            and detect_telegram_media_type(event.message) is None
        ):
            return

        metadata: dict[str, Any] = {}
        if chat_context.get("access_hash") is not None:
            metadata["access_hash"] = chat_context["access_hash"]
        if chat_context.get("avatar_url"):
            metadata["avatar_url"] = chat_context["avatar_url"]

        await event_sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="telegram",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                text=text,
                from_id=from_id,
                sent_at=sent_at,
                title=chat_context["title"],
                is_group=chat_context["is_group"],
                metadata=metadata,
            )
        )

    @client.on(events.NewMessage())
    async def on_new_message(event: Any) -> None:
        if not client_state.running:
            return
        try:
            if event.out:
                await _handle_outgoing_message(event)
            else:
                await _handle_incoming_message(event)
        except Exception:
            direction = "outgoing" if event.out else "incoming"
            logger.exception(
                "failed to persist %s telegram message account=%s",
                direction,
                account_id[:8],
            )

    @client.on(events.MessageRead())
    async def on_message_read(event: Any) -> None:
        if not client_state.running or delivery_tracker is None:
            return
        if getattr(event, "inbox", False):
            return
        max_id = getattr(event, "max_id", None)
        if max_id is None:
            return
        try:
            chat = await event.get_chat()
            external_chat_id = str(utils.get_peer_id(chat))
        except Exception:
            logger.debug("telegram read receipt: failed to resolve chat", exc_info=True)
            return
        try:
            await delivery_tracker.mark_up_to_external_id(
                account_id,
                external_chat_id=external_chat_id,
                max_external_id=int(max_id),
                status="read",
            )
        except Exception:
            logger.exception(
                "failed to apply telegram read receipt account=%s chat=%s",
                account_id[:8],
                external_chat_id,
            )


async def run_telegram_session_worker(
    *,
    settings: Settings,
    account_id: str,
    credentials: dict[str, Any],
    client_state: TelegramAccountClient,
    manager: TelegramClientManager,
    event_sink: EventSink,
    incoming_handler: IncomingMessageHandler | None = None,
) -> None:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    from allchats_sdk.events import ChatsDiscoveredEvent
    from allchats_sdk.providers.telegram.proxy import resolve_telegram_proxy
    from allchats_sdk.providers.telegram.qr_worker import (
        _persist_authorized,
        telegram_connect_timeout,
    )

    session_data = str(credentials.get("session_data") or "").strip()
    if not session_data:
        manager.set_client_state(account_id, state_instance="notAuthorized", running=False)
        return

    session = StringSession(session_data)
    proxy = resolve_telegram_proxy(settings=settings, credentials=credentials)
    connect_timeout = telegram_connect_timeout(proxy)
    via = "direct"
    if proxy:
        via = f"{proxy.get('proxy_type', 'socks5')}://{proxy.get('addr')}:{proxy.get('port')}"
    logger.info(
        "telegram session connect account=%s via %s timeout=%ss",
        account_id[:8],
        via,
        int(connect_timeout),
    )
    client = TelegramClient(
        session,
        settings.telegram.app_id,
        settings.telegram.app_hash,
        proxy=proxy,
        connection_retries=3,
        retry_delay=2,
        timeout=20,
    )
    client_state.telethon_client = client

    try:
        await asyncio.wait_for(client.connect(), timeout=connect_timeout)
        if not await client.is_user_authorized():
            manager.set_client_state(account_id, state_instance="notAuthorized", running=False)
            return

        me = await client.get_me()
        await _persist_authorized(
            account_id=account_id,
            credentials=credentials,
            client=client,
            me=me,
            manager=manager,
            count_auth=False,
        )
        _register_message_handlers(
            client=client,
            account_id=account_id,
            client_state=client_state,
            event_sink=event_sink,
            incoming_handler=incoming_handler,
            delivery_tracker=getattr(manager, "_delivery_tracker", None),
            media_storage=getattr(manager, "_media_storage", None),
        )
        from allchats_sdk.providers.telegram.calls import telegram_call_coordinator

        telegram_call_coordinator.register_handlers(client, account_id)
        from allchats_sdk.providers.telegram.entities import ensure_entity_cache

        await ensure_entity_cache(client)
        client_state.entities_loaded = True
        await event_sink.on_chats_discovered(
            ChatsDiscoveredEvent(
                connection_id=account_id,
                provider="telegram",
                runtime=client,
            )
        )

        while client_state.running:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        message = "telegram session connect timeout"
        logger.error("telegram session worker timeout account=%s", account_id[:8])
        manager.set_client_state(
            account_id,
            state_instance="error",
            error=message,
            running=False,
        )
        return
    except Exception as exc:
        logger.exception("telegram session worker failed account=%s", account_id[:8])
        manager.set_client_state(
            account_id,
            state_instance="error",
            error=str(exc),
            running=False,
        )
    finally:
        client_state.telethon_client = None
        await client.disconnect()
