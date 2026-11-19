from telethon.tl import types
from telethon.tl.types import (
    SendMessageCancelAction,
    SendMessageTypingAction,
    UpdateChannelUserTyping,
    UpdateChatUserTyping,
    UpdateUserTyping,
)

from allchats_sdk.providers.telegram.typing import describe_telegram_typing
from allchats_sdk.providers.vk.native_api import CHAT_START_ID, parse_typing_update


def test_vk_dialog_typing() -> None:
    parsed = parse_typing_update([61, 4242, 1])
    assert parsed == [{
        "external_chat_id": "4242",
        "user_id": "4242",
        "is_group": False,
    }]


def test_vk_chat_typing_uses_peer_id() -> None:
    parsed = parse_typing_update([62, 7, 15])
    assert parsed == [{
        "external_chat_id": str(CHAT_START_ID + 15),
        "user_id": "7",
        "is_group": True,
    }]


def test_vk_many_typers() -> None:
    peer_id = CHAT_START_ID + 3
    parsed = parse_typing_update([63, "11,12", peer_id, 2, 100])
    assert [item["user_id"] for item in parsed] == ["11", "12"]
    assert all(item["external_chat_id"] == str(peer_id) for item in parsed)


def test_vk_ignores_messages() -> None:
    assert parse_typing_update([4, 1, 0, 2, 3, "hi"]) == []


def test_telegram_private_typing() -> None:
    described = describe_telegram_typing(
        UpdateUserTyping(user_id=55, action=SendMessageTypingAction()),
    )
    assert described == {
        "external_chat_id": "55",
        "user_id": "55",
        "is_group": False,
    }


def test_telegram_group_typing_peer_id() -> None:
    described = describe_telegram_typing(
        UpdateChatUserTyping(
            chat_id=9,
            from_id=types.PeerUser(user_id=3),
            action=SendMessageTypingAction(),
        ),
    )
    assert described == {
        "external_chat_id": "-9",
        "user_id": "3",
        "is_group": True,
    }


def test_telegram_channel_typing_peer_id() -> None:
    described = describe_telegram_typing(
        UpdateChannelUserTyping(
            channel_id=777,
            top_msg_id=None,
            from_id=types.PeerUser(user_id=4),
            action=SendMessageTypingAction(),
        ),
    )
    assert described is not None
    assert described["user_id"] == "4"
    assert described["is_group"] is True
    assert described["external_chat_id"].startswith("-100")


def test_telegram_cancel_is_not_typing() -> None:
    described = describe_telegram_typing(
        UpdateUserTyping(user_id=1, action=SendMessageCancelAction()),
    )
    assert described is None
