"""MAX user display name resolution."""

from __future__ import annotations

from typing import Any


def _user_display_name(user: Any) -> str | None:
    names = getattr(user, "names", None) or []
    for item in names:
        full = str(getattr(item, "name", "") or "").strip()
        if full:
            return full
        first = str(getattr(item, "first_name", "") or "").strip()
        last = str(getattr(item, "last_name", "") or "").strip()
        combined = " ".join(part for part in (first, last) if part).strip()
        if combined:
            return combined
    return None


async def resolve_max_user_display_name(client: Any, user_id: int | str | None) -> str | None:
    if client is None or user_id is None:
        return None
    try:
        resolved_id = int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        users = await client.get_users([resolved_id])
    except Exception:
        return None
    for user in users or []:
        try:
            if int(getattr(user, "id", 0)) != resolved_id:
                continue
        except (TypeError, ValueError):
            continue
        return _user_display_name(user)
    return None


async def resolve_max_user_display_names(
    client: Any,
    user_ids: list[int | str],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    if client is None or not user_ids:
        return resolved
    unique_ids: list[int] = []
    for raw in user_ids:
        try:
            unique_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    unique_ids = list(dict.fromkeys(unique_ids))
    if not unique_ids:
        return resolved
    try:
        users = await client.get_users(unique_ids)
    except Exception:
        return resolved
    for user in users or []:
        name = _user_display_name(user)
        if not name:
            continue
        try:
            resolved[str(int(getattr(user, "id", 0)))] = name
        except (TypeError, ValueError):
            continue
    return resolved
