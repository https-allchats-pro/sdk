from __future__ import annotations

import json
from typing import Any

AVATAR_URL_PARTICIPANT_PREFIX = "avatar_url:"
AVITO_LISTING_PARTICIPANT_PREFIX = "avito_listing:"


def chat_avatar_api_path(account_id: str, external_chat_id: str) -> str:
    return f"/api/accounts/{account_id}/chats/{external_chat_id}/avatar"


def is_protected_avatar_url(url: str | None) -> bool:
    normalized = str(url or "").strip()
    return normalized.startswith("/api/")


def merge_stored_avatar_url(
    existing: list[str],
    *,
    avatar_url: str | None = None,
) -> list[str]:
    participants = [
        item
        for item in existing
        if not item.startswith(AVATAR_URL_PARTICIPANT_PREFIX)
    ]
    if avatar_url:
        url = avatar_url.strip()
        if url:
            participants.append(f"{AVATAR_URL_PARTICIPANT_PREFIX}{url}")
    return participants


def parse_stored_avatar_url(participants: list[str]) -> str | None:
    for item in participants:
        if item.startswith(AVATAR_URL_PARTICIPANT_PREFIX):
            url = item[len(AVATAR_URL_PARTICIPANT_PREFIX) :].strip()
            if url:
                return url
    return None


def merge_stored_avito_listing(
    existing: list[str],
    *,
    listing: dict[str, Any] | None,
) -> list[str]:
    participants = [
        item
        for item in existing
        if not item.startswith(AVITO_LISTING_PARTICIPANT_PREFIX)
    ]
    if not listing:
        return participants
    participants.append(
        f"{AVITO_LISTING_PARTICIPANT_PREFIX}{json.dumps(listing, ensure_ascii=False, separators=(',', ':'))}"
    )
    return participants


def parse_stored_avito_listing(participants: list[str]) -> dict[str, Any] | None:
    for item in participants:
        if not item.startswith(AVITO_LISTING_PARTICIPANT_PREFIX):
            continue
        raw = item[len(AVITO_LISTING_PARTICIPANT_PREFIX) :].strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed:
            return parsed
    return None


DISCORD_META_PARTICIPANT_PREFIX = "discord_meta:"


def merge_stored_discord_meta(
    existing: list[str],
    *,
    meta: dict[str, Any] | None,
) -> list[str]:
    participants = [
        item
        for item in existing
        if not item.startswith(DISCORD_META_PARTICIPANT_PREFIX)
    ]
    if not meta:
        return participants
    participants.append(
        f"{DISCORD_META_PARTICIPANT_PREFIX}{json.dumps(meta, ensure_ascii=False, separators=(',', ':'))}"
    )
    return participants


def parse_stored_discord_meta(participants: list[str]) -> dict[str, Any] | None:
    for item in participants:
        if not item.startswith(DISCORD_META_PARTICIPANT_PREFIX):
            continue
        raw = item[len(DISCORD_META_PARTICIPANT_PREFIX) :].strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and parsed:
            return parsed
    return None
