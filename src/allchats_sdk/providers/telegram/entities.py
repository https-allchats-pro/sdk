from __future__ import annotations

import logging
from typing import Any

from allchats_sdk.types.chat_metadata import chat_avatar_api_path
from allchats_sdk.errors import ValidationError

logger = logging.getLogger(__name__)


def input_peer_from_id(peer_id: int, access_hash: int) -> Any:
    from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser

    if peer_id >= 0:
        return InputPeerUser(peer_id, access_hash)
    if peer_id <= -1000000000000:
        channel_id = -(peer_id + 1000000000000)
        return InputPeerChannel(channel_id, access_hash)
    return InputPeerChat(-peer_id)


async def ensure_entity_cache(client: Any) -> None:
    await client.get_dialogs()


async def find_entity_in_dialogs(client: Any, peer_id: int) -> Any | None:
    from telethon import utils

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if dialog.id == peer_id or utils.get_peer_id(entity) == peer_id:
            return entity
    return None


async def resolve_send_entity(
    client: Any,
    chat_id: str,
    *,
    access_hash: int | None = None,
) -> Any:
    raw = chat_id.strip()
    if not raw:
        raise ValidationError("chat_id is required")

    if raw.startswith("@"):
        return await client.get_entity(raw)

    if raw.lstrip("-").isdigit():
        peer_id = int(raw)
        try:
            return await client.get_input_entity(peer_id)
        except (ValueError, TypeError):
            pass

        entity = await find_entity_in_dialogs(client, peer_id)
        if entity is not None:
            return entity

        if access_hash is not None:
            return input_peer_from_id(peer_id, access_hash)

        raise ValidationError(
            f"cannot resolve telegram entity {raw}; use phone_number or open the chat in Telegram first"
        )

    return await client.get_entity(raw)


def entity_can_send_messages(entity: Any) -> bool | None:
    """Whether the logged-in user can post in this Telegram peer.

    Broadcast channels and groups that ban send_messages return False.
    Unknown entity types return None so callers keep the previous value.
    """
    from telethon.tl.types import Channel, Chat, User

    if isinstance(entity, User):
        return True

    if isinstance(entity, Chat):
        if getattr(entity, "left", False) or getattr(entity, "kicked", False) or getattr(entity, "deactivated", False):
            return False
        return True

    if not isinstance(entity, Channel):
        return None

    if getattr(entity, "left", False) or getattr(entity, "kicked", False):
        return False

    creator = bool(getattr(entity, "creator", False))
    admin = getattr(entity, "admin_rights", None)
    is_broadcast = bool(getattr(entity, "broadcast", False)) and not bool(getattr(entity, "megagroup", False))
    if is_broadcast:
        return creator or bool(admin is not None and getattr(admin, "post_messages", False))

    if creator or admin is not None:
        return True

    banned = getattr(entity, "banned_rights", None)
    if banned is not None and getattr(banned, "send_messages", False):
        return False
    default_banned = getattr(entity, "default_banned_rights", None)
    if default_banned is not None and getattr(default_banned, "send_messages", False):
        return False
    return True


def describe_entity(entity: Any, *, external_id: str) -> tuple[str, bool]:
    from telethon.tl.types import Channel, Chat, User

    if isinstance(entity, User):
        first = str(getattr(entity, "first_name", "") or "").strip()
        last = str(getattr(entity, "last_name", "") or "").strip()
        title = " ".join(part for part in (first, last) if part).strip()
        if not title:
            username = str(getattr(entity, "username", "") or "").strip()
            title = f"@{username}" if username else external_id
        return title, False

    if isinstance(entity, (Chat, Channel)):
        return str(getattr(entity, "title", "") or external_id), True

    return external_id, False


async def resolve_sender_display_name(event: Any, sender_id: str) -> str | None:
    """Best-effort display name for a Telegram group message sender."""
    try:
        sender = await event.get_sender()
    except Exception:
        logger.debug("failed to resolve telegram sender entity", exc_info=True)
        return None
    if sender is None:
        return None
    title, _ = describe_entity(sender, external_id=sender_id)
    resolved = str(title or "").strip()
    return resolved or None


async def entity_avatar_url(
    client: Any,
    entity: Any,
    *,
    account_id: str | None = None,
    external_chat_id: str | None = None,
    media_storage: Any | None = None,
    download_big: bool = False,
) -> str | None:
    """Save a Telegram profile photo locally.

    Lists use the small photo (``download_big=False``). The large one is
    requested only after a chat is opened.
    """
    if (
        not download_big
        and media_storage is not None
        and account_id
        and external_chat_id
    ):
        try:
            if media_storage.read_avatar(account_id, external_chat_id):
                return None
        except Exception:
            pass

    data = None
    try:
        data = await client.download_profile_photo(
            entity,
            file=bytes,
            download_big=download_big,
        )
    except Exception:
        logger.debug("failed to download telegram profile photo", exc_info=True)

    if data and media_storage is not None and account_id and external_chat_id:
        media_storage.save_avatar(
            account_id=account_id,
            external_chat_id=external_chat_id,
            data=data,
        )
        version = "b" if download_big else "s"
        return f"{chat_avatar_api_path(account_id, external_chat_id)}?v={version}"

    username = str(getattr(entity, "username", "") or "").strip()
    if username:
        size = "320" if download_big else "160"
        return f"https://t.me/i/userpic/{size}/{username}.jpg"
    return None


async def describe_peer(telethon: Any, peer: Any) -> tuple[str, bool, str]:
    from telethon import utils
    from telethon.tl.types import Channel, Chat, User

    entity = await telethon.get_entity(peer)
    external_id = str(utils.get_peer_id(entity))
    if isinstance(entity, User):
        first = str(getattr(entity, "first_name", "") or "").strip()
        last = str(getattr(entity, "last_name", "") or "").strip()
        title = " ".join(part for part in (first, last) if part).strip()
        if not title:
            username = str(getattr(entity, "username", "") or "").strip()
            title = f"@{username}" if username else external_id
        return title, False, external_id

    if isinstance(entity, (Chat, Channel)):
        return str(getattr(entity, "title", "") or external_id), True, external_id

    return external_id, False, external_id
