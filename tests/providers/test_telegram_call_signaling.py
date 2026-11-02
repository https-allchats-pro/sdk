"""ntgcalls 3 renamed the call-signaling methods."""

from __future__ import annotations

import unittest

from allchats_sdk.providers.telegram.calls import (
    TelegramCallCoordinator,
    _CallSession,
)


class _NTgCallsV3:
    def __init__(self) -> None:
        self.signaling_callback = None
        self.sent: list[tuple[int, bytes]] = []

    def on_signaling_data(self, callback) -> None:
        self.signaling_callback = callback

    def on_connection_change(self, _callback) -> None:
        return None

    def on_frames(self, _callback) -> None:
        return None

    def on_remote_source_change(self, _callback) -> None:
        return None

    def send_signaling_data(self, user_id: int, data: bytes) -> None:
        self.sent.append((int(user_id), bytes(data)))


class TelegramCallSignalingTests(unittest.IsolatedAsyncioTestCase):
    async def test_inbound_signaling_uses_send_signaling_data(self) -> None:
        engine = _NTgCallsV3()
        coordinator = TelegramCallCoordinator()
        coordinator._ntgcalls = engine
        session = _CallSession(
            account_id="account01",
            call_id=5,
            peer=object(),
            g_a_hash=b"\x00" * 32,
            video=False,
            participant_id=42,
            operator_user_id="",
        )
        coordinator._sessions[("account01", 5)] = session

        await coordinator._handle_signaling_data("account01", 5, b"candidate")

        self.assertEqual(engine.sent, [(42, b"candidate")])

    def test_callback_registers_on_signaling_data(self) -> None:
        engine = _NTgCallsV3()
        coordinator = TelegramCallCoordinator()
        coordinator._ntgcalls = engine

        coordinator._register_ntgcalls_callbacks()

        self.assertTrue(coordinator._ntgcalls_callbacks_registered)
        self.assertIsNotNone(engine.signaling_callback)
        engine.signaling_callback(7, b"offer")


if __name__ == "__main__":
    unittest.main()
