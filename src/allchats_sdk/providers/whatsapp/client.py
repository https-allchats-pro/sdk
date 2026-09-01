from __future__ import annotations

import base64
import io
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import segno

logger = logging.getLogger(__name__)


def normalize_recipient(value: str) -> str:
    raw = value.strip()
    if not raw:
        return raw
    if "@" in raw:
        raw = raw.split("@", 1)[0]
    digits = re.sub(r"\D", "", raw)
    return digits or raw.lstrip("+")


def phone_to_chat_id(phone_number: str) -> str:
    digits = normalize_recipient(phone_number)
    if not digits:
        raise ValueError("phone_number is invalid")
    return f"{digits}@c.us"


def qr_bytes_to_data_url(data: bytes) -> str:
    buffer = io.BytesIO()
    segno.make_qr(data).save(buffer, kind="png", scale=6)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def unwrap_whatsapp_message(message: Any) -> Any:
    if message is None:
        return message

    device_sent = getattr(message, "deviceSentMessage", None)
    if device_sent is not None:
        inner = getattr(device_sent, "message", None)
        if inner is not None:
            return inner

    return message


def is_whatsapp_outgoing_message(source: Any, message: Any | None = None) -> bool:
    if bool(getattr(source, "IsFromMe", False)):
        return True
    return message is not None and getattr(message, "deviceSentMessage", None) is not None


def _jid_from_destination_string(destination: str) -> Any | None:
    raw = str(destination or "").strip()
    if not raw:
        return None
    try:
        return external_chat_id_to_jid(raw)
    except ValueError:
        logger.debug("whatsapp invalid destination jid %s", raw, exc_info=True)
        return None


def resolve_outgoing_chat_jid(
    source: Any,
    *,
    info: Any | None = None,
    message: Any | None = None,
) -> Any:
    from neonize.utils.jid import jid_is_lid

    is_group = bool(getattr(source, "IsGroup", False))
    chat = getattr(source, "Chat", None)
    recipient_alt = getattr(source, "RecipientAlt", None)

    if is_group:
        return chat or recipient_alt

    for candidate in (chat, recipient_alt):
        if candidate is None or getattr(candidate, "IsEmpty", False):
            continue
        if jid_is_lid(candidate):
            return candidate

    if chat is not None and not getattr(chat, "IsEmpty", False):
        return chat
    if recipient_alt is not None and not getattr(recipient_alt, "IsEmpty", False):
        return recipient_alt

    if info is not None:
        meta = getattr(info, "DeviceSentMeta", None)
        destination_jid = _jid_from_destination_string(
            str(getattr(meta, "DestinationJID", "") or ""),
        )
        if destination_jid is not None:
            return destination_jid

    if message is not None:
        device_sent = getattr(message, "deviceSentMessage", None)
        destination_jid = _jid_from_destination_string(
            str(getattr(device_sent, "destinationJID", "") or ""),
        )
        if destination_jid is not None:
            return destination_jid

    return chat or recipient_alt


def resolve_message_chat_jid(
    source: Any,
    *,
    info: Any | None = None,
    message: Any | None = None,
) -> Any:
    if is_whatsapp_outgoing_message(source, message):
        return resolve_outgoing_chat_jid(source, info=info, message=message)
    return resolve_incoming_chat_jid(source)


def extract_message_text(message: Any) -> str:
    if message is None:
        return ""

    message = unwrap_whatsapp_message(message)

    conversation = str(getattr(message, "conversation", "") or "").strip()
    if conversation:
        return conversation

    extended = getattr(message, "extendedTextMessage", None)
    if extended is not None:
        text = str(getattr(extended, "text", "") or "").strip()
        if text:
            return text

    image = getattr(message, "imageMessage", None)
    if image is not None:
        return str(getattr(image, "caption", "") or "").strip()

    video = getattr(message, "videoMessage", None)
    if video is not None:
        return str(getattr(video, "caption", "") or "").strip()

    document = getattr(message, "documentMessage", None)
    if document is not None:
        return str(getattr(document, "caption", "") or "").strip()

    return ""


def jid_user_part(jid: Any) -> str:
    return str(getattr(jid, "User", "") or "").strip()


def lookup_lid_for_pn_in_session_db(session_db_path: Path, pn_user: str) -> str | None:
    pn = normalize_recipient(pn_user) or pn_user.strip()
    if not pn or not session_db_path.exists():
        return None

    try:
        with sqlite3.connect(f"file:{session_db_path}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT lid FROM whatsmeow_lid_map WHERE pn = ?",
                (pn,),
            ).fetchone()
            if row and row[0]:
                return str(row[0]).strip()
    except Exception:
        logger.debug("whatsapp lid sqlite lookup failed for pn=%s", pn[:8], exc_info=True)
    return None


def save_lid_mapping_to_session_db(session_db_path: Path, lid_user: str, pn_user: str) -> None:
    lid = lid_user.strip()
    pn = normalize_recipient(pn_user) or pn_user.strip()
    if not lid or not pn or not session_db_path.parent.exists():
        return

    try:
        with sqlite3.connect(session_db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS whatsmeow_lid_map ("
                "lid TEXT PRIMARY KEY, pn TEXT UNIQUE NOT NULL"
                ")",
            )
            conn.execute(
                "INSERT OR IGNORE INTO whatsmeow_lid_map (lid, pn) VALUES (?, ?)",
                (lid, pn),
            )
            conn.commit()
    except Exception:
        logger.debug("whatsapp lid sqlite save failed lid=%s", lid[:8], exc_info=True)


def persist_lid_mapping_from_source(session_db_path: Path, source: Any) -> None:
    from neonize.utils.jid import jid_is_lid

    chat = getattr(source, "Chat", None)
    sender = getattr(source, "Sender", None)
    sender_alt = getattr(source, "SenderAlt", None)

    pairs: list[tuple[str, str]] = []
    for primary, alt in ((sender, sender_alt), (chat, sender_alt)):
        if primary is None or alt is None:
            continue
        if getattr(primary, "IsEmpty", False) or getattr(alt, "IsEmpty", False):
            continue
        if jid_is_lid(primary) and not jid_is_lid(alt):
            pairs.append((jid_user_part(primary), jid_user_part(alt)))
        elif jid_is_lid(alt) and not jid_is_lid(primary):
            pairs.append((jid_user_part(alt), jid_user_part(primary)))

    for lid_user, pn_user in pairs:
        save_lid_mapping_to_session_db(session_db_path, lid_user, pn_user)


def jid_to_external_chat_id(jid: Any) -> str:
    if jid is None or getattr(jid, "IsEmpty", False):
        return ""
    try:
        from neonize.utils.jid import JIDToNonAD, Jid2String

        return Jid2String(JIDToNonAD(jid))
    except Exception:
        logger.debug("whatsapp jid_to_external_chat_id fallback", exc_info=True)

    user = str(getattr(jid, "User", "") or "").strip()
    server = str(getattr(jid, "Server", "") or "s.whatsapp.net").strip()
    if not user:
        return ""
    if "@" in user:
        return user
    if not server:
        server = "s.whatsapp.net"
    return f"{user}@{server}"


def resolve_incoming_chat_jid(source: Any) -> Any:
    from neonize.utils.jid import jid_is_lid

    is_group = bool(getattr(source, "IsGroup", False))
    chat = getattr(source, "Chat", None)
    sender = getattr(source, "Sender", None)
    sender_alt = getattr(source, "SenderAlt", None)

    if is_group:
        return chat or sender

    for candidate in (chat, sender, sender_alt):
        if candidate is None or getattr(candidate, "IsEmpty", False):
            continue
        if jid_is_lid(candidate):
            return candidate

    return chat or sender or sender_alt


def external_chat_id_to_jid(external_chat_id: str):
    from neonize.utils.jid import build_jid

    raw = external_chat_id.strip()
    if not raw:
        raise ValueError("external_chat_id is empty")
    if "@" in raw:
        user, server = raw.split("@", 1)
        user = normalize_recipient(user) or user
        if server == "c.us":
            server = "s.whatsapp.net"
        return build_jid(user, server)
    digits = normalize_recipient(raw)
    if not digits:
        raise ValueError("external_chat_id is invalid")
    return build_jid(digits)


def parse_message_timestamp(value: Any) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=UTC)
    seconds = getattr(value, "seconds", None)
    if seconds is not None:
        nanos = int(getattr(value, "nanos", 0) or 0)
        return datetime.fromtimestamp(int(seconds) + nanos / 1e9, tz=UTC)
    return datetime.now(UTC)
