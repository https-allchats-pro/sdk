"""Telegram contact search."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

from allchats_sdk.providers.telegram.entities import describe_peer, entity_avatar_url

logger = logging.getLogger(__name__)

PHONE_QUERY_RE = re.compile(r"^\+?[\d\s().-]{5,}$")


@dataclass(slots=True)
class ContactSearchResult:
    external_chat_id: str
    title: str
    subtitle: str | None = None
    avatar_url: str | None = None
    is_group: bool = False
    phone_number: str | None = None


async def search_telegram_contacts(
    client: Any,
    query: str,
    limit: int,
) -> list[ContactSearchResult]:
    results: list[ContactSearchResult] = []
    seen: set[str] = set()

    def add_item(item: ContactSearchResult) -> None:
        if item.external_chat_id in seen:
            return
        seen.add(item.external_chat_id)
        results.append(item)

    if query.startswith("@"):
        await _add_entity(client, query, add_item)

    if PHONE_QUERY_RE.match(query):
        await _add_phone(client, query, add_item)

    if len(results) < limit:
        await _add_global_search(client, query, limit, add_item, seen)

    if len(results) < limit:
        await _add_dialog_matches(client, query, limit, add_item, seen)

    return results[:limit]


async def _add_entity(
    client: Any,
    query: str,
    add_item: Callable[[ContactSearchResult], None],
) -> None:
    from telethon.tl.types import User

    try:
        entity = await client.get_entity(query)
    except Exception:
        return

    title, is_group, external_chat_id = await describe_peer(client, entity)
    if not external_chat_id:
        return

    subtitle = None
    if isinstance(entity, User):
        username = str(getattr(entity, "username", "") or "").strip()
        if username:
            subtitle = f"@{username}"
        phone = str(getattr(entity, "phone", "") or "").strip()
        if phone:
            subtitle = f"+{phone}" if not phone.startswith("+") else phone

    avatar_url = await entity_avatar_url(client, entity)
    add_item(
        ContactSearchResult(
            external_chat_id=external_chat_id,
            title=title,
            subtitle=subtitle,
            avatar_url=avatar_url,
            is_group=is_group,
        )
    )


async def _add_phone(
    client: Any,
    query: str,
    add_item: Callable[[ContactSearchResult], None],
) -> None:
    from telethon.tl.functions.contacts import ResolvePhoneRequest
    from telethon.tl.types import User

    phone = query.strip()
    if not phone.startswith("+"):
        phone = f"+{phone.lstrip('+')}"

    try:
        result = await client(ResolvePhoneRequest(phone=phone))
    except Exception:
        return

    users = getattr(result, "users", None) or []
    if not users:
        return

    entity = users[0]
    if not isinstance(entity, User):
        return

    title, is_group, external_chat_id = await describe_peer(client, entity)
    if not external_chat_id:
        return

    avatar_url = await entity_avatar_url(client, entity)
    add_item(
        ContactSearchResult(
            external_chat_id=external_chat_id,
            title=title,
            subtitle=phone,
            avatar_url=avatar_url,
            is_group=is_group,
            phone_number=phone,
        )
    )


async def _add_global_search(
    client: Any,
    query: str,
    limit: int,
    add_item: Callable[[ContactSearchResult], None],
    seen: set[str],
) -> None:
    from telethon.tl.functions.contacts import SearchRequest
    from telethon.tl.types import Channel, Chat, User

    from allchats_sdk.providers.telegram.peers import get_peer_id

    try:
        found = await client(SearchRequest(q=query, limit=limit))
    except Exception as exc:
        logger.warning("telegram contact search failed: %s", exc)
        return

    users = {user.id: user for user in getattr(found, "users", None) or []}
    for chat in getattr(found, "chats", None) or []:
        if len(seen) >= limit:
            break
        if isinstance(chat, (Chat, Channel)):
            title = str(getattr(chat, "title", "") or "").strip()
            external_chat_id = str(get_peer_id(chat))
            if not title:
                title = external_chat_id
            add_item(
                ContactSearchResult(
                    external_chat_id=external_chat_id,
                    title=title,
                    subtitle="group" if isinstance(chat, Chat) else "channel",
                    is_group=True,
                )
            )

    for user in users.values():
        if len(seen) >= limit:
            break
        if not isinstance(user, User) or getattr(user, "bot", False) or getattr(user, "deleted", False):
            continue

        title, _, external_chat_id = await describe_peer(client, user)
        if not external_chat_id:
            continue

        username = str(getattr(user, "username", "") or "").strip()
        phone = str(getattr(user, "phone", "") or "").strip()
        subtitle = f"@{username}" if username else (f"+{phone}" if phone else None)
        avatar_url = await entity_avatar_url(client, user)
        add_item(
            ContactSearchResult(
                external_chat_id=external_chat_id,
                title=title,
                subtitle=subtitle,
                avatar_url=avatar_url,
                phone_number=f"+{phone}" if phone and not phone.startswith("+") else phone or None,
            )
        )


async def _add_dialog_matches(
    client: Any,
    query: str,
    limit: int,
    add_item: Callable[[ContactSearchResult], None],
    seen: set[str],
) -> None:
    lowered = query.casefold()
    async for dialog in client.iter_dialogs():
        if len(seen) >= limit:
            break

        name = str(getattr(dialog, "name", "") or "").strip()
        if not name or lowered not in name.casefold():
            continue

        entity = dialog.entity
        title, is_group, external_chat_id = await describe_peer(client, entity)
        if not external_chat_id:
            continue

        avatar_url = await entity_avatar_url(client, entity)
        add_item(
            ContactSearchResult(
                external_chat_id=external_chat_id,
                title=title or name,
                subtitle=name if title and title != name else None,
                avatar_url=avatar_url,
                is_group=is_group,
            )
        )
