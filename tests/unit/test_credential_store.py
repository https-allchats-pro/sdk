"""CredentialStore persistence tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from allchats_sdk.clients._wiring import PersistingEventSink, load_credentials
from allchats_sdk.credential_store import FileCredentialStore, MemoryCredentialStore
from allchats_sdk.events import CredentialsUpdatedEvent


class CredentialStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_roundtrip(self) -> None:
        store = MemoryCredentialStore()
        await store.save("acc-1", {"session_data": "abc", "user_id": "1"})
        loaded = await store.get("acc-1")
        self.assertEqual(loaded, {"session_data": "abc", "user_id": "1"})
        await store.clear("acc-1")
        self.assertIsNone(await store.get("acc-1"))

    async def test_file_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = FileCredentialStore(path)
            await store.save("acc-1", {"session_data": "xyz", "device_id": "acc-1"})
            self.assertTrue(path.exists())
            loaded = await store.get("acc-1")
            self.assertEqual(loaded["session_data"], "xyz")
            await store.clear("acc-1")
            self.assertFalse(path.exists())

    async def test_persisting_event_sink_saves_credentials(self) -> None:
        store = MemoryCredentialStore()
        sink = PersistingEventSink(store)
        await sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id="acc-1",
                provider="telegram",
                credentials={"session_data": "s", "user_id": "42"},
            )
        )
        loaded = await store.get("acc-1")
        self.assertEqual(loaded["user_id"], "42")

    async def test_persisting_event_sink_clears_credentials(self) -> None:
        store = MemoryCredentialStore()
        await store.save("acc-1", {"session_data": "s"})
        sink = PersistingEventSink(store)
        await sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id="acc-1",
                provider="telegram",
                credentials={},
                clear=True,
            )
        )
        self.assertIsNone(await store.get("acc-1"))

    async def test_load_credentials_defaults(self) -> None:
        store = MemoryCredentialStore()
        loaded = await load_credentials(
            store,
            "acc-1",
            defaults={"user_id": "", "session_data": ""},
        )
        self.assertEqual(loaded["device_id"], "acc-1")
        self.assertEqual(loaded["session_data"], "")


if __name__ == "__main__":
    unittest.main()
