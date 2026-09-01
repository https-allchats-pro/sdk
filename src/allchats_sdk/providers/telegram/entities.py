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
) -> str | None:
    username = str(getattr(entity, "username", "") or "").strip()
    if username:
        return f"https://t.me/i/userpic/320/{username}.jpg"

    if media_storage is None or not account_id or not external_chat_id:
        return None

    try:
        data = await client.download_profile_photo(entity, file=bytes)
    except Exception:
        logger.debug("failed to download telegram profile photo", exc_info=True)
        return None

    if not data:
        return None

    media_storage.save_avatar(
        account_id=account_id,
        external_chat_id=external_chat_id,
        data=data,
    )
    return chat_avatar_api_path(account_id, external_chat_id)


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
