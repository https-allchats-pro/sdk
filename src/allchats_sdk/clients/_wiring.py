"""Internal helpers shared by account clients."""

from __future__ import annotations

from typing import Any

from allchats_sdk.credential_store import CredentialStore
from allchats_sdk.protocols import EventSink, NullEventSink


class PersistingEventSink:
    """EventSink that writes credentials to a :class:`CredentialStore`."""

    def __init__(
        self,
        store: CredentialStore,
        *,
        inner: EventSink | None = None,
    ) -> None:
        self._store = store
        self._inner: EventSink = inner or NullEventSink()

    async def on_incoming(self, event: Any) -> None:
        await self._inner.on_incoming(event)

    async def on_outgoing(self, event: Any) -> None:
        await self._inner.on_outgoing(event)

    async def on_credentials_updated(self, event: Any) -> None:
        account_id = str(getattr(event, "connection_id", "") or "")
        if getattr(event, "clear", False):
            await self._store.clear(account_id)
        else:
            await self._store.save(account_id, dict(getattr(event, "credentials", None) or {}))
        await self._inner.on_credentials_updated(event)

    async def on_connection_state(self, event: Any) -> None:
        await self._inner.on_connection_state(event)

    async def on_chats_discovered(self, event: Any) -> None:
        await self._inner.on_chats_discovered(event)

    async def on_chat_id_remap(self, event: Any) -> None:
        await self._inner.on_chat_id_remap(event)


def resolve_event_sink(
    *,
    credential_store: CredentialStore | None,
    event_sink: EventSink | None,
) -> EventSink:
    if credential_store is None:
        return event_sink or NullEventSink()
    return PersistingEventSink(credential_store, inner=event_sink)


async def load_credentials(
    store: CredentialStore | None,
    account_id: str,
    *,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if store is not None:
        stored = await store.get(account_id)
        if stored:
            merged = dict(defaults or {})
            merged.update(stored)
            merged.setdefault("device_id", account_id)
            return merged
    payload = dict(defaults or {})
    payload.setdefault("device_id", account_id)
    return payload
