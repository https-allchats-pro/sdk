"""VK community / wall helpers built on ``vk_method`` / ``vk_method_async``."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from allchats_sdk.providers.vk.native_api import (
    VkNativeApiError,
    decode_message_text,
    vk_method,
    vk_method_async,
)

_CLUB_PREFIX_RE = re.compile(r"^(?:club|public|event)(\d+)$", re.IGNORECASE)
_WALL_URL_RE = re.compile(
    r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/(?:club|public|event|wall-?)?([A-Za-z0-9_.]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VkGroup:
    """Resolved VK community (positive ``id``)."""

    id: int
    name: str
    screen_name: str

    @property
    def owner_id(self) -> int:
        """Wall owner id for community posts (negative)."""
        return -self.id


@dataclass(frozen=True)
class WallPost:
    """Single wall post from ``wall.get``."""

    id: int
    owner_id: int
    date: int
    text: str
    group_id: int
    group_name: str
    group_screen_name: str

    @property
    def url(self) -> str:
        return f"https://vk.com/wall{self.owner_id}_{self.id}"

    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.date)


def normalize_group_ref(group: str | int) -> str:
    """Normalize screen name / numeric id / URL to a ``groups.getById`` argument."""
    if isinstance(group, int):
        return str(abs(group))

    raw = str(group).strip()
    if not raw:
        raise ValueError("group is required")

    if "://" in raw or raw.startswith("vk.com") or raw.startswith("vk.ru"):
        match = _WALL_URL_RE.search(raw)
        if match:
            raw = match.group(1)

    raw = raw.lstrip("/")
    if raw.startswith("-") and raw[1:].isdigit():
        return raw[1:]

    club = _CLUB_PREFIX_RE.match(raw)
    if club:
        return club.group(1)

    return raw


def _parse_groups_response(response: Any) -> list[dict[str, Any]]:
    if isinstance(response, list):
        return [item for item in response if isinstance(item, dict)]
    if isinstance(response, dict):
        groups = response.get("groups")
        if isinstance(groups, list):
            return [item for item in groups if isinstance(item, dict)]
        # Some responses return a single group object.
        if response.get("id") is not None:
            return [response]
    return []


def _group_from_payload(payload: dict[str, Any]) -> VkGroup:
    group_id = int(payload.get("id") or 0)
    if group_id <= 0:
        raise VkNativeApiError("failed to resolve vk group id")
    name = str(payload.get("name") or group_id).strip() or str(group_id)
    screen_name = str(payload.get("screen_name") or group_id).strip() or str(group_id)
    return VkGroup(id=group_id, name=name, screen_name=screen_name)


def resolve_group(
    group: str | int,
    *,
    access_token: str,
    proxies: dict[str, str] | None = None,
) -> VkGroup:
    """Resolve screen name or numeric id to ``VkGroup`` via ``groups.getById``."""
    group_ref = normalize_group_ref(group)
    response = vk_method(
        "groups.getById",
        access_token=access_token,
        group_ids=group_ref,
        fields="screen_name",
        proxies=proxies,
    )
    items = _parse_groups_response(response)
    if not items:
        raise VkNativeApiError(f"group not found: {group_ref}")
    return _group_from_payload(items[0])


async def resolve_group_async(
    group: str | int,
    *,
    access_token: str,
    proxies: dict[str, str] | None = None,
) -> VkGroup:
    return await asyncio.to_thread(
        resolve_group,
        group,
        access_token=access_token,
        proxies=proxies,
    )


def _wall_items(response: Any) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    items = response.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _post_from_item(item: dict[str, Any], *, group: VkGroup) -> WallPost | None:
    post_id = int(item.get("id") or 0)
    if post_id <= 0:
        return None
    owner_id = int(item.get("owner_id") or group.owner_id)
    date = int(item.get("date") or 0)
    text = decode_message_text(str(item.get("text") or ""))
    # Copy text from attachments/link descriptions is out of scope; use wall text only.
    return WallPost(
        id=post_id,
        owner_id=owner_id,
        date=date,
        text=text,
        group_id=group.id,
        group_name=group.name,
        group_screen_name=group.screen_name,
    )


def iter_wall_posts_sync(
    group: VkGroup | str | int,
    *,
    access_token: str,
    since: datetime | None = None,
    until: datetime | None = None,
    page_size: int = 100,
    max_pages: int | None = None,
    proxies: dict[str, str] | None = None,
) -> Iterator[WallPost]:
    """Paginate ``wall.get`` newest-first; stop when posts are older than ``since``."""
    resolved = (
        group
        if isinstance(group, VkGroup)
        else resolve_group(group, access_token=access_token, proxies=proxies)
    )
    count = max(1, min(int(page_size), 100))
    since_ts = int(since.timestamp()) if since is not None else None
    until_ts = int(until.timestamp()) if until is not None else None
    offset = 0
    pages = 0

    while True:
        if max_pages is not None and pages >= max_pages:
            break

        response = vk_method(
            "wall.get",
            access_token=access_token,
            owner_id=resolved.owner_id,
            count=count,
            offset=offset,
            filter="owner",
            proxies=proxies,
        )
        items = _wall_items(response)
        if not items:
            break

        pages += 1
        stop = False
        for item in items:
            post = _post_from_item(item, group=resolved)
            if post is None:
                continue
            if until_ts is not None and post.date > until_ts:
                continue
            if since_ts is not None and post.date < since_ts:
                stop = True
                break
            yield post

        if stop or len(items) < count:
            break
        offset += count


async def iter_wall_posts(
    group: VkGroup | str | int,
    *,
    access_token: str,
    since: datetime | None = None,
    until: datetime | None = None,
    page_size: int = 100,
    max_pages: int | None = None,
    proxies: dict[str, str] | None = None,
) -> AsyncIterator[WallPost]:
    """Async pagination over community wall posts (see ``iter_wall_posts_sync``)."""
    resolved = (
        group
        if isinstance(group, VkGroup)
        else await resolve_group_async(group, access_token=access_token, proxies=proxies)
    )
    count = max(1, min(int(page_size), 100))
    since_ts = int(since.timestamp()) if since is not None else None
    until_ts = int(until.timestamp()) if until is not None else None
    offset = 0
    pages = 0

    while True:
        if max_pages is not None and pages >= max_pages:
            break

        response = await vk_method_async(
            "wall.get",
            access_token=access_token,
            owner_id=resolved.owner_id,
            count=count,
            offset=offset,
            filter="owner",
            proxies=proxies,
        )
        items = _wall_items(response)
        if not items:
            break

        pages += 1
        stop = False
        for item in items:
            post = _post_from_item(item, group=resolved)
            if post is None:
                continue
            if until_ts is not None and post.date > until_ts:
                continue
            if since_ts is not None and post.date < since_ts:
                stop = True
                break
            yield post

        if stop or len(items) < count:
            break
        offset += count
