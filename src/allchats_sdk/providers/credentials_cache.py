"""In-memory credentials cache for provider managers."""

from __future__ import annotations

from typing import Any

from allchats_sdk.errors import ValidationError


class CredentialsCache:
    def __init__(self) -> None:
        self._by_connection: dict[str, dict[str, Any]] = {}

    def set(self, connection_id: str, credentials: dict[str, Any]) -> None:
        self._by_connection[connection_id] = dict(credentials or {})

    def update(self, connection_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        merged = dict(self._by_connection.get(connection_id) or {})
        merged.update(patch or {})
        self._by_connection[connection_id] = merged
        return merged

    def get(self, connection_id: str) -> dict[str, Any]:
        creds = self._by_connection.get(connection_id)
        if creds is None:
            raise ValidationError(
                f"no cached credentials for connection {connection_id}; connect first"
            )
        return creds

    def get_or_empty(self, connection_id: str) -> dict[str, Any]:
        return dict(self._by_connection.get(connection_id) or {})

    def pop(self, connection_id: str) -> None:
        self._by_connection.pop(connection_id, None)

    def has(self, connection_id: str) -> bool:
        return connection_id in self._by_connection
