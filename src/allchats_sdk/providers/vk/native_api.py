from __future__ import annotations

import asyncio
import html
import random
from enum import IntEnum
from typing import Any

import requests

API_VERSION = "5.199"
API_BASE = "https://api.vk.ru/method"
CLIENT_ID = 2274003
CLIENT_SECRET = "hHbZxrka2uZ6jB1inYsH"
SCOPE = 4096  # messages
REDIRECT_URI = "https://oauth.vk.ru/blank.html"
USER_AGENT = (
    "VKAndroidApp/8.45-12345 (Android 13; SDK 33; armeabi-v7a; samsung SM-G991B; ru)"
)

CHAT_START_ID = int(2e9)
LONGPOLL_WAIT_SEC = 25
LONGPOLL_MODE = 2 + 8 + 32 + 64 + 128


class VkNativeApiError(Exception):
    pass


class VkMessageFlag(IntEnum):
    OUTBOX = 2
    MEDIA = 512


class VkEventType(IntEnum):
    MESSAGE_NEW = 4
    MESSAGE_READ_OUTBOX = 7


def parse_read_outbox_update(update: list[Any]) -> dict[str, Any] | None:
    """Peer read our outgoing messages up to local_id (VK longpoll type 7)."""
    if len(update) < 3:
        return None
    if update[0] != VkEventType.MESSAGE_READ_OUTBOX:
        return None
    try:
        peer_id = int(update[1])
        max_message_id = int(update[2])
    except (TypeError, ValueError):
        return None
    from allchats_sdk.providers.vk.client import external_chat_id_from_peer

    return {
        "peer_id": peer_id,
        "max_message_id": max_message_id,
        "external_chat_id": external_chat_id_from_peer(peer_id),
    }


def api_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "X-Origin": "https://vk.ru",
        "Content-Type": "application/x-www-form-urlencoded",
    }


def vk_method(
    method: str,
    *,
    access_token: str | None = None,
    proxies: dict[str, str] | None = None,
    **params: object,
) -> Any:
    payload = {key: str(value) for key, value in params.items()}
    payload["v"] = API_VERSION
    if access_token:
        payload["access_token"] = access_token

    response = requests.post(
        f"{API_BASE}/{method}",
        data=payload,
        headers=api_headers(),
        timeout=30,
        proxies=proxies,
    )
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        error = data["error"]
        message = error.get("error_msg") if isinstance(error, dict) else str(error)
        raise VkNativeApiError(message or "vk api error")

    return data["response"]


async def vk_method_async(
    method: str,
    *,
    access_token: str | None = None,
    proxies: dict[str, str] | None = None,
    **params: object,
) -> Any:
    return await asyncio.to_thread(
        vk_method,
        method,
        access_token=access_token,
        proxies=proxies,
        **params,
    )


def send_message(
    *,
    access_token: str,
    peer_id: int,
    text: str,
    random_id: int | None = None,
    reply_to: int | None = None,
    forward_messages: str | None = None,
    proxies: dict[str, str] | None = None,
) -> int:
    resolved_random_id = random_id if random_id is not None else random.randint(1, 2_000_000_000)
    params: dict[str, object] = {
        "peer_id": peer_id,
        "message": text,
        "random_id": resolved_random_id,
    }
    if reply_to is not None:
        params["reply_to"] = reply_to
    if forward_messages:
        params["forward_messages"] = forward_messages
    message_id = vk_method(
        "messages.send",
        access_token=access_token,
        proxies=proxies,
        **params,
    )
    return int(message_id)


async def send_message_async(
    *,
    access_token: str,
    peer_id: int,
    text: str,
    random_id: int | None = None,
    reply_to: int | None = None,
    forward_messages: str | None = None,
    proxies: dict[str, str] | None = None,
) -> int:
    return await asyncio.to_thread(
        send_message,
        access_token=access_token,
        peer_id=peer_id,
        text=text,
        random_id=random_id,
        reply_to=reply_to,
        forward_messages=forward_messages,
        proxies=proxies,
    )


VK_REACTION_EMOJI_TO_ID: dict[str, int] = {
    "❤️": 1,
    "❤": 1,
    "🔥": 2,
    "😂": 3,
    "👍": 4,
    "👎": 5,
    "😍": 6,
    "😮": 7,
    "😢": 8,
    "🙏": 9,
    "👏": 10,
    "🤔": 11,
    "🤯": 12,
    "🤬": 13,
    "😱": 14,
    "🎉": 15,
    "💩": 16,
}


def send_reaction(
    *,
    access_token: str,
    peer_id: int,
    cmid: int,
    reaction_id: int,
    proxies: dict[str, str] | None = None,
) -> None:
    vk_method(
        "messages.sendReaction",
        access_token=access_token,
        peer_id=peer_id,
        cmid=cmid,
        reaction_id=reaction_id,
        proxies=proxies,
    )


async def send_reaction_async(
    *,
    access_token: str,
    peer_id: int,
    cmid: int,
    reaction_id: int,
    proxies: dict[str, str] | None = None,
) -> None:
    await asyncio.to_thread(
        send_reaction,
        access_token=access_token,
        peer_id=peer_id,
        cmid=cmid,
        reaction_id=reaction_id,
        proxies=proxies,
    )


def delete_reaction(
    *,
    access_token: str,
    peer_id: int,
    cmid: int,
    proxies: dict[str, str] | None = None,
) -> None:
    vk_method(
        "messages.deleteReaction",
        access_token=access_token,
        peer_id=peer_id,
        cmid=cmid,
        proxies=proxies,
    )


async def delete_reaction_async(
    *,
    access_token: str,
    peer_id: int,
    cmid: int,
    proxies: dict[str, str] | None = None,
) -> None:
    await asyncio.to_thread(
        delete_reaction,
        access_token=access_token,
        peer_id=peer_id,
        cmid=cmid,
        proxies=proxies,
    )


def delete_messages(
    *,
    access_token: str,
    message_ids: list[int],
    peer_id: int | None = None,
    delete_for_all: bool = True,
    proxies: dict[str, str] | None = None,
) -> None:
    params: dict[str, object] = {
        "message_ids": ",".join(str(item) for item in message_ids),
        "delete_for_all": 1 if delete_for_all else 0,
    }
    if peer_id is not None:
        params["peer_id"] = peer_id
    vk_method(
        "messages.delete",
        access_token=access_token,
        proxies=proxies,
        **params,
    )


async def delete_messages_async(
    *,
    access_token: str,
    message_ids: list[int],
    peer_id: int | None = None,
    delete_for_all: bool = True,
    proxies: dict[str, str] | None = None,
) -> None:
    await asyncio.to_thread(
        delete_messages,
        access_token=access_token,
        message_ids=message_ids,
        peer_id=peer_id,
        delete_for_all=delete_for_all,
        proxies=proxies,
    )


def get_conversation_message_id(
    *,
    access_token: str,
    message_id: int,
    proxies: dict[str, str] | None = None,
) -> int | None:
    response = vk_method(
        "messages.getById",
        access_token=access_token,
        message_ids=message_id,
        proxies=proxies,
    )
    items = response.get("items") if isinstance(response, dict) else None
    if not isinstance(items, list) or not items:
        return None
    item = items[0]
    if not isinstance(item, dict):
        return None
    cmid = item.get("conversation_message_id")
    if cmid is None:
        return None
    return int(cmid)


async def get_conversation_message_id_async(
    *,
    access_token: str,
    message_id: int,
    proxies: dict[str, str] | None = None,
) -> int | None:
    return await asyncio.to_thread(
        get_conversation_message_id,
        access_token=access_token,
        message_id=message_id,
        proxies=proxies,
    )


def get_user_info(*, access_token: str, proxies: dict[str, str] | None = None) -> dict[str, Any]:
    users = vk_method(
        "users.get",
        access_token=access_token,
        fields="photo_50,photo_100",
        proxies=proxies,
    )
    if isinstance(users, list) and users and isinstance(users[0], dict):
        return users[0]
    raise VkNativeApiError("failed to resolve vk user")


def extract_user_avatar_url(user: dict[str, Any]) -> str | None:
    for key in ("photo_100", "photo_50", "photo_200"):
        value = str(user.get(key) or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
    return None


def get_user_profiles(
    *,
    access_token: str,
    user_ids: list[int],
    proxies: dict[str, str] | None = None,
) -> dict[int, dict[str, str | None]]:
    if not user_ids:
        return {}

    unique_ids = list(dict.fromkeys(user_ids))
    users = vk_method(
        "users.get",
        access_token=access_token,
        user_ids=",".join(str(user_id) for user_id in unique_ids),
        fields="photo_50,photo_100",
        proxies=proxies,
    )
    profiles: dict[int, dict[str, str | None]] = {}
    if not isinstance(users, list):
        return profiles

    for user in users:
        if not isinstance(user, dict):
            continue
        user_id = int(user.get("id") or 0)
        if not user_id:
            continue
        first = str(user.get("first_name") or "").strip()
        last = str(user.get("last_name") or "").strip()
        full_name = " ".join(part for part in (first, last) if part).strip()
        profiles[user_id] = {
            "name": full_name or str(user_id),
            "avatar_url": extract_user_avatar_url(user),
        }
    return profiles


def get_user_names(*, access_token: str, user_ids: list[int]) -> dict[int, str]:
    profiles = get_user_profiles(access_token=access_token, user_ids=user_ids)
    return {
        user_id: str(profile.get("name") or user_id)
        for user_id, profile in profiles.items()
    }


def peer_id_to_external_chat_id(peer: dict[str, Any]) -> str | None:
    if not isinstance(peer, dict):
        return None

    peer_type = str(peer.get("type") or "").strip().lower()
    peer_id = int(peer.get("id") or 0)
    if not peer_id:
        return None

    if peer_type == "user":
        return str(peer_id)
    if peer_type == "chat":
        return str(CHAT_START_ID + peer_id)
    if peer_type == "group":
        return str(-peer_id)
    if peer_type == "email":
        return str(peer_id)
    return str(peer_id)


def conversation_title(
    peer: dict[str, Any],
    *,
    profiles: dict[int, dict[str, str | None]],
    groups: dict[int, str],
) -> str:
    peer_type = str(peer.get("type") or "").strip().lower()
    peer_id = int(peer.get("id") or 0)
    if peer_type == "user":
        profile = profiles.get(peer_id)
        if profile and profile.get("name"):
            return str(profile["name"])
    if peer_type in {"group", "chat"}:
        title = groups.get(peer_id)
        if title:
            return title
    local_id = int(peer.get("local_id") or 0)
    if local_id:
        return str(local_id)
    return str(peer_id)


def conversation_avatar_url(
    peer: dict[str, Any],
    *,
    profiles: dict[int, dict[str, str | None]],
) -> str | None:
    peer_type = str(peer.get("type") or "").strip().lower()
    if peer_type != "user":
        return None
    peer_id = int(peer.get("id") or 0)
    profile = profiles.get(peer_id)
    if profile is None:
        return None
    avatar = profile.get("avatar_url")
    return str(avatar) if avatar else None


def parse_conversation_profiles(response: dict[str, Any]) -> dict[int, dict[str, str | None]]:
    profiles: dict[int, dict[str, str | None]] = {}
    users = response.get("profiles")
    if not isinstance(users, list):
        return profiles

    for user in users:
        if not isinstance(user, dict):
            continue
        user_id = int(user.get("id") or 0)
        if not user_id:
            continue
        first = str(user.get("first_name") or "").strip()
        last = str(user.get("last_name") or "").strip()
        full_name = " ".join(part for part in (first, last) if part).strip()
        profiles[user_id] = {
            "name": full_name or str(user_id),
            "avatar_url": extract_user_avatar_url(user),
        }
    return profiles


def parse_conversation_groups(response: dict[str, Any]) -> dict[int, str]:
    groups: dict[int, str] = {}
    items = response.get("groups")
    if not isinstance(items, list):
        return groups

    for group in items:
        if not isinstance(group, dict):
            continue
        group_id = int(group.get("id") or 0)
        if not group_id:
            continue
        title = str(group.get("name") or group_id).strip()
        groups[group_id] = title or str(group_id)
    return groups


def decode_message_text(text: str) -> str:
    normalized = text.replace("<br>", "\n").replace("<br />", "\n")
    return html.unescape(normalized)


def parse_message_update(update: list[Any]) -> dict[str, Any] | None:
    if len(update) < 6:
        return None
    if update[0] != VkEventType.MESSAGE_NEW:
        return None

    message_id = update[1]
    flags = int(update[2])
    is_outgoing = bool(flags & VkMessageFlag.OUTBOX)

    peer_id = int(update[3])
    timestamp = int(update[4])
    text = decode_message_text(str(update[5] or ""))

    # LongPoll MESSAGE_NEW layout (mode & 2):
    # [4, id, flags, peer_id, ts, text, extra_values, attachments, random_id]
    # Attachment hints (attach1_type, attach1_kind=audiomsg, ...) live in update[7],
    # not in extra_values — reading only [6] drops empty-text voice messages.
    extra_values = update[6] if len(update) > 6 and isinstance(update[6], dict) else {}
    attachment_values = update[7] if len(update) > 7 and isinstance(update[7], dict) else {}
    attach_meta = {**extra_values, **attachment_values}

    from_id = peer_id
    if peer_id > CHAT_START_ID:
        raw_from = extra_values.get("from")
        if raw_from is not None:
            from_id = int(raw_from)

    from allchats_sdk.providers.vk.client import external_chat_id_from_peer
    from allchats_sdk.providers.vk.voice import (
        parse_longpoll_has_attachments,
        parse_longpoll_has_voice_hint,
    )

    has_voice = parse_longpoll_has_voice_hint(attach_meta)
    has_attachments = parse_longpoll_has_attachments(attach_meta) or bool(
        flags & VkMessageFlag.MEDIA
    )
    if not text.strip() and not has_voice and not has_attachments:
        return None

    title_peer_id = peer_id if is_outgoing else from_id

    return {
        "message_id": str(message_id),
        "peer_id": peer_id,
        "from_id": from_id,
        "title_peer_id": title_peer_id,
        "timestamp": timestamp,
        "text": text,
        "external_chat_id": external_chat_id_from_peer(peer_id),
        "has_voice": has_voice,
        "has_attachments": has_attachments,
        "is_outgoing": is_outgoing,
    }


def parse_incoming_message_update(update: list[Any]) -> dict[str, Any] | None:
    parsed = parse_message_update(update)
    if parsed is None or parsed.get("is_outgoing"):
        return None
    return parsed


class NativeLongPoll:
    def __init__(self, access_token: str, *, proxies: dict[str, str] | None = None) -> None:
        self.access_token = access_token
        self._proxies = proxies
        self.session = requests.Session()
        if proxies:
            self.session.proxies.update(proxies)
        self.key: str | None = None
        self.server: str | None = None
        self.ts: str | None = None
        self.url: str | None = None
        self.update_server(update_ts=True)

    def update_server(self, *, update_ts: bool = True) -> None:
        response = vk_method(
            "messages.getLongPollServer",
            access_token=self.access_token,
            lp_version=3,
            need_pts=1,
            proxies=self._proxies,
        )
        self.key = str(response["key"])
        self.server = str(response["server"])
        self.url = f"https://{self.server}"
        if update_ts:
            self.ts = str(response["ts"])

    def check(self, *, wait: int = LONGPOLL_WAIT_SEC) -> list[list[Any]]:
        if not self.url or not self.key or self.ts is None:
            raise VkNativeApiError("longpoll server is not initialized")

        response = self.session.get(
            self.url,
            params={
                "act": "a_check",
                "key": self.key,
                "ts": self.ts,
                "wait": wait,
                "mode": LONGPOLL_MODE,
                "version": 3,
            },
            timeout=wait + 10,
        )
        response.raise_for_status()
        data = response.json()

        if "failed" not in data:
            self.ts = str(data["ts"])
            updates = data.get("updates")
            return updates if isinstance(updates, list) else []

        failed = int(data["failed"])
        if failed == 1:
            self.ts = str(data["ts"])
            return []
        if failed == 2:
            self.update_server(update_ts=False)
            return []
        if failed == 3:
            self.update_server(update_ts=True)
            return []

        raise VkNativeApiError(f"longpoll failed with code {failed}")
