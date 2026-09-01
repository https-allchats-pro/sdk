from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from typing import TYPE_CHECKING, Any

from google.protobuf.message import DecodeError
from neonize.aioze.client import NewAClient
from neonize.aioze.events import ConnectedEv, LoggedOutEv, MessageEv, ReceiptEv
from neonize.exc import SendMessageError
from neonize.proto.Neonize_pb2 import Receipt as ReceiptProto
from neonize.proto.Neonize_pb2 import SendMessageReturnFunction
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
from neonize._binder import free_bytes
from neonize.utils.jid import build_jid, jid_is_lid

from allchats_sdk.providers.whatsapp.client import (
    external_chat_id_to_jid,
    extract_message_text,
    jid_to_external_chat_id,
    lookup_lid_for_pn_in_session_db,
    normalize_recipient,
    parse_message_timestamp,
    persist_lid_mapping_from_source,
    qr_bytes_to_data_url,
    is_whatsapp_outgoing_message,
    resolve_message_chat_jid,
)
from allchats_sdk.providers.whatsapp.proxy import resolve_whatsapp_proxy, whatsapp_proxy_label
from allchats_sdk.config import Settings
from allchats_sdk.events import IncomingMessageEvent, OutgoingMessageEvent

if TYPE_CHECKING:
    from allchats_sdk.providers.whatsapp.manager import (
        WhatsAppAccountClient,
        WhatsAppClientManager,
    )
    from allchats_sdk.protocols import EventSink, IncomingMessageHandler

logger = logging.getLogger(__name__)

SESSION_DB_NAME = "neonize.db"


def whatsapp_session_db(settings: Settings, account_id: str):
    from pathlib import Path

    return Path(settings.work_dir) / "whatsapp" / account_id / SESSION_DB_NAME


def ensure_whatsapp_session_db(settings: Settings, account_id: str):
    db_path = whatsapp_session_db(settings, account_id)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


async def run_whatsapp_neonize_runtime(
    *,
    settings: Settings,
    account_id: str,
    client_state: WhatsAppAccountClient,
    manager: WhatsAppClientManager,
    event_sink: EventSink,
    incoming_handler: IncomingMessageHandler | None = None,
    credentials: dict[str, Any] | None = None,
) -> None:
    session_db = ensure_whatsapp_session_db(settings, account_id)

    # neonize Go layer is not safe for concurrent NewAClient/connect
    # ("fatal error: concurrent map writes"). Serialize bootstrap only.
    await manager.neonize_bootstrap_lock.acquire()
    bootstrap_held = True
    try:
        client = NewAClient(str(session_db))
        manager.register_neonize_client(account_id, client)
    except Exception:
        manager.neonize_bootstrap_lock.release()
        raise

    @client.qr
    async def on_qr(_: NewAClient, data: bytes) -> None:
        runtime = manager.client_for_account(account_id)
        if runtime is None:
            return
        runtime.qr_data_url = qr_bytes_to_data_url(data)
        runtime.state_instance = "starting"

    @client.event(ConnectedEv)
    async def on_connected(_: NewAClient, __: ConnectedEv) -> None:
        await _authorize_if_logged_in(manager, account_id, client)

    @client.event(LoggedOutEv)
    async def on_logged_out(_: NewAClient, ___: LoggedOutEv) -> None:
        manager.set_client_state(account_id, state_instance="notAuthorized", running=False)

    @client.event(MessageEv)
    async def on_message(neonize_client: NewAClient, event: MessageEv) -> None:
        if not client_state.running:
            return

        source = event.Info.MessageSource
        message_proto = event.Message
        persist_lid_mapping_from_source(session_db, source)
        is_from_me = is_whatsapp_outgoing_message(source, message_proto)
        chat_jid = resolve_message_chat_jid(source, info=event.Info, message=message_proto)
        sender_jid = getattr(source, "Sender", None) or chat_jid
        if chat_jid is None:
            return

        external_chat_id = jid_to_external_chat_id(chat_jid)
        if not external_chat_id:
            return

        sender = jid_to_external_chat_id(sender_jid) if sender_jid is not None else external_chat_id
        title = str(getattr(chat_jid, "User", "") or external_chat_id).strip() or external_chat_id
        message_id = str(getattr(event.Info, "ID", "") or "").strip()
        if not message_id:
            return

        is_group = external_chat_id.endswith("@g.us")
        timestamp = getattr(event.Info, "Timestamp", None) or getattr(event.Info, "timestamp", None)
        sent_at = parse_message_timestamp(timestamp)
        from_id = str(client_state.user_id or account_id)
        from_name = None
        if is_group and not is_from_me:
            push_name = (
                getattr(event.Info, "PushName", None)
                or getattr(event.Info, "push_name", None)
                or getattr(source, "PushName", None)
            )
            from_name = str(push_name or "").strip() or None

        if is_from_me:
            pass

        if incoming_handler is not None:
            if is_from_me:
                await incoming_handler.process_whatsapp_outgoing(
                    account_id=account_id,
                    neonize_client=neonize_client,
                    message_proto=message_proto,
                    external_chat_id=external_chat_id,
                    title=title,
                    is_group=is_group,
                    from_=from_id,
                    sent_at=sent_at,
                    external_message_id=message_id,
                )
            else:
                await incoming_handler.process_whatsapp_incoming(
                    account_id=account_id,
                    neonize_client=neonize_client,
                    message_proto=message_proto,
                    external_chat_id=external_chat_id,
                    title=title,
                    is_group=is_group,
                    from_=sender,
                    sent_at=sent_at,
                    external_message_id=message_id,
                    from_name=from_name,
                )
            return

        text = extract_message_text(message_proto)
        if not text:
            return

        if is_from_me:
            await event_sink.on_outgoing(
                OutgoingMessageEvent(
                    connection_id=account_id,
                    provider="whatsapp",
                    external_chat_id=external_chat_id,
                    external_message_id=message_id,
                    text=text,
                    from_id=from_id,
                    sent_at=sent_at,
                    title=title,
                    is_group=is_group,
                )
            )
            return

        metadata: dict[str, Any] = {}
        if from_name:
            metadata["from_name"] = from_name

        await event_sink.on_incoming(
            IncomingMessageEvent(
                connection_id=account_id,
                provider="whatsapp",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                from_id=sender,
                text=text,
                sent_at=sent_at,
                title=title,
                is_group=is_group,
                metadata=metadata,
            )
        )

    @client.event(ReceiptEv)
    async def on_receipt(_: NewAClient, event: ReceiptEv) -> None:
        delivery_tracker = getattr(manager, "_delivery_tracker", None)
        if not client_state.running or delivery_tracker is None:
            return
        source = getattr(event, "MessageSource", None)
        chat_jid = getattr(source, "Chat", None) if source is not None else None
        if chat_jid is None:
            return
        external_chat_id = jid_to_external_chat_id(chat_jid)
        if not external_chat_id:
            return
        receipt_type = int(getattr(event, "Type", 0) or 0)
        message_ids = [str(item) for item in (getattr(event, "MessageIDs", None) or []) if str(item)]
        if not message_ids:
            return
        if receipt_type == ReceiptProto.ReceiptType.DELIVERED:
            status = "delivered"
        elif receipt_type in (
            ReceiptProto.ReceiptType.READ,
            ReceiptProto.ReceiptType.PLAYED,
        ):
            status = "read"
        else:
            return
        try:
            await delivery_tracker.mark_by_external_ids(
                account_id,
                external_chat_id=external_chat_id,
                external_ids=message_ids,
                status=status,
            )
        except Exception:
            logger.exception(
                "failed to apply whatsapp receipt account=%s chat=%s type=%s",
                account_id[:8],
                external_chat_id,
                receipt_type,
            )

    manager.set_client_state(account_id, state_instance="starting", running=True)

    proxy_settings = resolve_whatsapp_proxy(settings, credentials)
    proxy_label = whatsapp_proxy_label(settings, credentials)
    if proxy_settings is not None:
        logger.info(
            "whatsapp connecting via proxy %s account=%s",
            proxy_label,
            account_id[:8],
        )

    try:
        try:
            await client.connect(proxy_settings)
            await _authorize_if_logged_in(manager, account_id, client)
        finally:
            if bootstrap_held:
                manager.neonize_bootstrap_lock.release()
                bootstrap_held = False
        await client.idle()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("whatsapp neonize runtime failed account=%s: %s", account_id[:8], exc)
        existing = manager.client_for_account(account_id)
        if existing is None or existing.state_instance != "authorized":
            from allchats_sdk.observability import record_auth

            record_auth("whatsapp", "failed")
        manager.set_client_state(
            account_id,
            state_instance="notAuthorized",
            error=str(exc),
            running=False,
        )
    finally:
        if bootstrap_held:
            manager.neonize_bootstrap_lock.release()
            bootstrap_held = False
        manager.unregister_neonize_client(account_id)
        try:
            await client.disconnect()
        except Exception:
            logger.debug("whatsapp neonize disconnect failed account=%s", account_id[:8], exc_info=True)


def clear_session_dir(settings: Settings, account_id: str) -> None:
    session_dir = whatsapp_session_db(settings, account_id).parent
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)


def _neonize_go_client(client: NewAClient):
    return object.__getattribute__(client, "_NewAClient__client")


async def neonize_is_connected(client: NewAClient) -> bool:
    return bool(await _neonize_go_client(client).IsConnected(client.uuid))


async def neonize_is_logged_in(client: NewAClient) -> bool:
    return bool(await _neonize_go_client(client).IsLoggedIn(client.uuid))


async def neonize_client_is_ready(client: NewAClient) -> bool:
    try:
        return bool(
            await neonize_is_connected(client)
            and await neonize_is_logged_in(client)
            and getattr(client, "me", None) is not None
        )
    except Exception:
        logger.debug("whatsapp neonize readiness check failed", exc_info=True)
        return False


async def _authorize_if_logged_in(
    manager: WhatsAppClientManager,
    account_id: str,
    client: NewAClient,
) -> None:
    if not await neonize_is_logged_in(client):
        return
    await manager.on_authorized(account_id, neonize_client=client)


def _is_lid_send_error(exc: Exception) -> bool:
    message = str(exc).casefold()
    return any(
        fragment in message
        for fragment in (
            "store doesn't contain a device jid",
            "no lid found",
            "failed to get device list",
            "websocket not connected",
        )
    )


async def _try_get_lid_from_pn(client: NewAClient, pn_jid: Any) -> Any | None:
    if not await neonize_client_is_ready(client):
        return None
    try:
        lid_jid = await client.get_lid_from_pn(pn_jid)
        if lid_jid is not None and not getattr(lid_jid, "IsEmpty", False):
            return lid_jid
    except Exception:
        logger.debug("whatsapp get_lid_from_pn failed", exc_info=True)
    return None


async def resolve_send_jid(
    client: NewAClient,
    *,
    external_chat_id: str | None,
    phone_digits: str,
    session_db: Any | None = None,
):
    from pathlib import Path

    target = str(external_chat_id or "").strip()
    digits = normalize_recipient(phone_digits)

    if target:
        jid = external_chat_id_to_jid(target)
    elif digits:
        jid = build_jid(digits)
    else:
        raise ValueError("recipient is not configured")

    server = str(getattr(jid, "Server", "") or "").strip()
    if jid_is_lid(jid) or server == "g.us":
        return jid

    pn_user = str(getattr(jid, "User", "") or digits).strip()
    db_path = Path(session_db) if session_db is not None else None
    if db_path is not None and pn_user:
        lid_user = lookup_lid_for_pn_in_session_db(db_path, pn_user)
        if lid_user:
            return build_jid(lid_user, "lid")

    lid_jid = await _try_get_lid_from_pn(client, jid)
    if lid_jid is not None:
        return lid_jid

    return jid


async def _alternate_send_jid(
    client: NewAClient,
    current_jid: Any,
    *,
    phone_digits: str,
    session_db: Any | None,
) -> Any | None:
    from pathlib import Path

    server = str(getattr(current_jid, "Server", "") or "").strip()
    pn_user = normalize_recipient(phone_digits) or str(getattr(current_jid, "User", "") or "").strip()
    if not pn_user:
        return None

    if jid_is_lid(current_jid):
        return build_jid(pn_user)

    db_path = Path(session_db) if session_db is not None else None
    if db_path is not None:
        lid_user = lookup_lid_for_pn_in_session_db(db_path, pn_user)
        if lid_user:
            return build_jid(lid_user, "lid")

    return await _try_get_lid_from_pn(client, build_jid(pn_user))


def _parse_send_response_bytes(protobytes: bytes) -> str:
    try:
        model = SendMessageReturnFunction.FromString(protobytes)
    except DecodeError as exc:
        try:
            as_text = protobytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            as_text = ""
        if as_text:
            raise SendMessageError(as_text) from exc
        logger.warning(
            "whatsapp send response could not be decoded (%d bytes); assuming message was delivered",
            len(protobytes),
            exc_info=True,
        )
        return uuid.uuid4().hex.upper()

    if model.Error:
        raise SendMessageError(model.Error)

    message_id = str(getattr(model.SendResponse, "ID", "") or "").strip()
    if message_id:
        return message_id

    logger.warning("whatsapp send succeeded without message id in response")
    return uuid.uuid4().hex.upper()


async def _invoke_neonize_send(client: NewAClient, jid: Any, text: str) -> str:
    go_client = object.__getattribute__(client, "_NewAClient__client")
    to_bytes = jid.SerializeToString()
    msg = Message(conversation=text)
    message_bytes = msg.SerializeToString()

    bytes_ptr = await go_client.SendMessage(
        client.uuid,
        to_bytes,
        len(to_bytes),
        message_bytes,
        len(message_bytes),
    )
    protobytes = bytes_ptr.contents.get_bytes()
    free_bytes(bytes_ptr)

    if not protobytes:
        logger.warning("whatsapp send returned empty response; assuming message was delivered")
        return uuid.uuid4().hex.upper()

    return _parse_send_response_bytes(protobytes)


async def _send_neonize_once(client: NewAClient, jid: Any, text: str) -> tuple[str, str]:
    resolved_chat_id = jid_to_external_chat_id(jid)

    try:
        response = await client.send_message(jid, text)
        message_id = str(getattr(response, "ID", "") or getattr(response, "id", "") or "").strip()
    except SendMessageError:
        raise
    except Exception:
        logger.debug("whatsapp send_message failed, falling back to raw send", exc_info=True)
        try:
            message_id = await _invoke_neonize_send(client, jid, text)
        except (DecodeError, SendMessageError):
            logger.warning(
                "whatsapp fallback send response could not be parsed; assuming message was delivered",
                exc_info=True,
            )
            message_id = ""

    if not message_id:
        message_id = uuid.uuid4().hex.upper()

    return message_id, resolved_chat_id


async def send_neonize_message(
    client: NewAClient,
    *,
    external_chat_id: str | None,
    phone_digits: str,
    text: str,
    session_db: Any | None = None,
    reply_to_external_id: str | None = None,
    reply_to_sender: str | None = None,
    reply_to_text: str | None = None,
) -> tuple[str, str]:
    jid = await resolve_send_jid(
        client,
        external_chat_id=external_chat_id,
        phone_digits=phone_digits,
        session_db=session_db,
    )

    try:
        if reply_to_external_id:
            return await _send_neonize_reply_once(
                client,
                jid,
                text=text,
                reply_to_external_id=reply_to_external_id,
                reply_to_sender=reply_to_sender or jid_to_external_chat_id(jid),
                reply_to_text=reply_to_text or "",
            )
        return await _send_neonize_once(client, jid, text)
    except Exception as exc:
        if not _is_lid_send_error(exc):
            raise

        alt_jid = await _alternate_send_jid(
            client,
            jid,
            phone_digits=phone_digits,
            session_db=session_db,
        )
        if alt_jid is None or jid_to_external_chat_id(alt_jid) == jid_to_external_chat_id(jid):
            raise

        logger.info(
            "whatsapp retrying send via alternate jid %s",
            jid_to_external_chat_id(alt_jid),
        )
        if reply_to_external_id:
            return await _send_neonize_reply_once(
                client,
                alt_jid,
                text=text,
                reply_to_external_id=reply_to_external_id,
                reply_to_sender=reply_to_sender or jid_to_external_chat_id(alt_jid),
                reply_to_text=reply_to_text or "",
            )
        return await _send_neonize_once(client, alt_jid, text)


def _build_quoted_neonize_message(
    *,
    chat_jid: Any,
    sender_external_id: str,
    message_id: str,
    text: str,
) -> Any:
    from neonize.proto.Neonize_pb2 import Message as NeonizeMessage, MessageInfo, MessageSource

    sender_jid = external_chat_id_to_jid(sender_external_id) or chat_jid
    quoted = NeonizeMessage()
    quoted.Info.CopyFrom(
        MessageInfo(
            ID=message_id,
            MessageSource=MessageSource(
                Chat=chat_jid,
                Sender=sender_jid,
                IsFromMe=False,
                IsGroup=bool(str(getattr(chat_jid, "Server", "") or "") == "g.us"),
            ),
        )
    )
    quoted.Message.CopyFrom(Message(conversation=text or " "))
    return quoted


async def _send_neonize_reply_once(
    client: NewAClient,
    jid: Any,
    *,
    text: str,
    reply_to_external_id: str,
    reply_to_sender: str,
    reply_to_text: str,
) -> tuple[str, str]:
    quoted = _build_quoted_neonize_message(
        chat_jid=jid,
        sender_external_id=reply_to_sender,
        message_id=reply_to_external_id,
        text=reply_to_text,
    )
    response = await client.reply_message(text, quoted, to=jid)
    message_id = str(getattr(response, "ID", "") or getattr(response, "id", "") or "").strip()
    if not message_id:
        message_id = uuid.uuid4().hex.upper()
    return message_id, jid_to_external_chat_id(jid)


async def send_neonize_reaction(
    client: NewAClient,
    *,
    external_chat_id: str,
    sender_external_id: str,
    message_id: str,
    emoji: str,
    session_db: Any | None = None,
) -> None:
    phone_digits = normalize_recipient(
        external_chat_id.split("@", 1)[0] if "@" in external_chat_id else external_chat_id
    )
    jid = await resolve_send_jid(
        client,
        external_chat_id=external_chat_id,
        phone_digits=phone_digits,
        session_db=session_db,
    )
    sender_jid = external_chat_id_to_jid(sender_external_id) or jid
    reaction_msg = await client.build_reaction(jid, sender_jid, message_id, emoji)
    await client.send_message(jid, reaction_msg)


async def revoke_neonize_message(
    client: NewAClient,
    *,
    external_chat_id: str,
    sender_external_id: str,
    message_id: str,
    session_db: Any | None = None,
) -> None:
    phone_digits = normalize_recipient(
        external_chat_id.split("@", 1)[0] if "@" in external_chat_id else external_chat_id
    )
    jid = await resolve_send_jid(
        client,
        external_chat_id=external_chat_id,
        phone_digits=phone_digits,
        session_db=session_db,
    )
    sender_jid = external_chat_id_to_jid(sender_external_id) or jid
    await client.revoke_message(jid, sender_jid, message_id)


async def _send_neonize_media_once(
    client: NewAClient,
    jid: Any,
    *,
    data: bytes,
    message_type: str,
    filename: str | None,
    content_type: str | None,
    caption: str | None,
) -> tuple[str, str]:
    from allchats_sdk.providers.whatsapp.media import send_whatsapp_media_message

    resolved_chat_id = jid_to_external_chat_id(jid)
    message_id = await send_whatsapp_media_message(
        client,
        jid,
        data=data,
        message_type=message_type,
        filename=filename,
        content_type=content_type,
        caption=caption,
    )
    return message_id, resolved_chat_id


async def send_neonize_media(
    client: NewAClient,
    *,
    external_chat_id: str | None,
    phone_digits: str,
    data: bytes,
    message_type: str,
    filename: str | None = None,
    content_type: str | None = None,
    caption: str | None = None,
    session_db: Any | None = None,
) -> tuple[str, str]:
    jid = await resolve_send_jid(
        client,
        external_chat_id=external_chat_id,
        phone_digits=phone_digits,
        session_db=session_db,
    )

    try:
        return await _send_neonize_media_once(
            client,
            jid,
            data=data,
            message_type=message_type,
            filename=filename,
            content_type=content_type,
            caption=caption,
        )
    except Exception as exc:
        if not _is_lid_send_error(exc):
            raise

        alt_jid = await _alternate_send_jid(
            client,
            jid,
            phone_digits=phone_digits,
            session_db=session_db,
        )
        if alt_jid is None or jid_to_external_chat_id(alt_jid) == jid_to_external_chat_id(jid):
            raise

        logger.info(
            "whatsapp retrying media send via alternate jid %s",
            jid_to_external_chat_id(alt_jid),
        )
        return await _send_neonize_media_once(
            client,
            alt_jid,
            data=data,
            message_type=message_type,
            filename=filename,
            content_type=content_type,
            caption=caption,
        )
