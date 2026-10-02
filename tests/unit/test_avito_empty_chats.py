from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from allchats_sdk.providers.avito.sync_worker import (
    _chat_has_user_dialogue,
    _is_user_dialogue_message,
    _sync_chat,
)


class UserDialogueTests(unittest.IsolatedAsyncioTestCase):
    def test_system_message_is_not_a_dialogue(self) -> None:
        self.assertFalse(
            _is_user_dialogue_message(
                {"id": "1", "type": "system", "direction": "in", "author_id": 2},
                owner_user_id="1",
            )
        )

    def test_missing_last_message_is_not_a_dialogue(self) -> None:
        self.assertFalse(_is_user_dialogue_message(None, owner_user_id="1"))

    def test_incoming_text_is_a_dialogue(self) -> None:
        self.assertTrue(
            _is_user_dialogue_message(
                {"id": "1", "type": "text", "direction": "in", "author_id": 2},
                owner_user_id="1",
            )
        )

    def test_outgoing_text_is_a_dialogue(self) -> None:
        self.assertTrue(
            _is_user_dialogue_message(
                {"id": "1", "type": "text", "author_id": 7},
                owner_user_id="7",
            )
        )

    async def test_chat_without_last_message_has_no_dialogue(self) -> None:
        has_dialogue = await _chat_has_user_dialogue(
            {"id": "c1"},
            user_id="1",
            access_token="token",
            proxies=None,
        )
        self.assertFalse(has_dialogue)

    async def test_system_last_message_checks_history(self) -> None:
        with patch(
            "allchats_sdk.providers.avito.sync_worker.get_chat_messages",
            new=AsyncMock(
                return_value=[
                    {"id": "s", "type": "system", "direction": "in", "author_id": 2},
                ]
            ),
        ) as get_messages:
            has_dialogue = await _chat_has_user_dialogue(
                {
                    "id": "c1",
                    "last_message": {
                        "id": "s",
                        "type": "system",
                        "direction": "in",
                        "author_id": 2,
                    },
                },
                user_id="1",
                access_token="token",
                proxies=None,
            )
        self.assertFalse(has_dialogue)
        get_messages.assert_awaited_once()

    async def test_sync_skips_chat_without_dialogue(self) -> None:
        sink = AsyncMock()
        sink.on_chat_without_dialogue = AsyncMock()
        skipped: set[str] = set()

        await _sync_chat(
            "account-1",
            chat={"id": "chat-1", "users": []},
            user_id="1",
            access_token="token",
            event_sink=sink,
            seen_message_ids=set(),
            skipped_without_dialogue=skipped,
            bootstrapped=False,
            sync_started_at_ms=None,
            manager=AsyncMock(),
        )

        sink.on_chats_discovered.assert_not_called()
        sink.on_chat_without_dialogue.assert_awaited_once_with("account-1", "chat-1")
        self.assertIn("chat-1:", skipped)
