"""VK catalog helpers for search / statuses via ``vk_method``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from allchats_sdk.providers.vk.native_api import vk_method, vk_method_async

# Browser search/catalog UI uses a newer API version than messaging defaults.
CATALOG_API_VERSION = "5.288"
NEWSFEED_API_VERSION = "5.199"

# newsfeed.search rejects empty q; a single space returns a broad global feed.
DEFAULT_NEWSFEED_SEARCH_Q = " "


@dataclass(frozen=True)
class CatalogSearchTopPage:
    """Raw page from a VK catalog search method (SDK layer, not app domain)."""

    response: dict[str, Any]
    next_from: str | None
    method: str = "catalog.getSearchStatuses"


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_next_from(payload: Any) -> str | None:
    """Pull pagination cursor from known catalog response shapes.

    Only ``next_from`` / ``nextFrom`` are treated as the *next* page cursor.
    Do not read ``start_from`` here — VK often echoes the request cursor, which
    would stall pagination after the first page.
    """
    if not isinstance(payload, dict):
        return None

    for key in ("next_from", "nextFrom"):
        found = _as_optional_str(payload.get(key))
        if found:
            return found

    # Prefer next_from from the newsfeed_items block (statuses search).
    catalog = payload.get("catalog")
    if isinstance(catalog, dict):
        sections = catalog.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                blocks = section.get("blocks")
                if isinstance(blocks, list):
                    for block in blocks:
                        if not isinstance(block, dict):
                            continue
                        if str(block.get("data_type") or "") == "newsfeed_items":
                            found = _as_optional_str(block.get("next_from") or block.get("nextFrom"))
                            if found:
                                return found
                    for block in blocks:
                        if isinstance(block, dict):
                            found = _as_optional_str(
                                block.get("next_from") or block.get("nextFrom")
                            )
                            if found:
                                return found
                found = extract_next_from(section)
                if found:
                    return found
        found = extract_next_from(catalog)
        if found:
            return found
    return None


def _normalize_response(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if response is None:
        return {}
    return {"items": response}


def get_search_top(
    *,
    access_token: str,
    count: int = 100,
    start_from: str | None = None,
    q: str | None = None,
    api_version: str = CATALOG_API_VERSION,
    proxies: dict[str, str] | None = None,
    **extra: object,
) -> CatalogSearchTopPage:
    """Call ``catalog.getSearchTop`` (search UI: people/groups — usually no wall posts)."""
    params: dict[str, object] = {
        "count": max(1, int(count)),
        "need_blocks": 1,
        "v": api_version,
    }
    if start_from:
        params["start_from"] = start_from
    if q is not None and str(q).strip():
        params["q"] = str(q).strip()
    params.update(extra)

    response = _normalize_response(
        vk_method(
            "catalog.getSearchTop",
            access_token=access_token,
            proxies=proxies,
            **params,
        )
    )
    return CatalogSearchTopPage(
        response=response,
        next_from=extract_next_from(response),
        method="catalog.getSearchTop",
    )


def get_search_statuses(
    *,
    access_token: str,
    count: int = 100,
    start_from: str | None = None,
    q: str | None = None,
    api_version: str = CATALOG_API_VERSION,
    proxies: dict[str, str] | None = None,
    **extra: object,
) -> CatalogSearchTopPage:
    """Call ``catalog.getSearchStatuses`` — global/search wall posts (newsfeed_items)."""
    params: dict[str, object] = {
        "count": max(1, int(count)),
        "need_blocks": 1,
        "v": api_version,
    }
    if start_from:
        params["start_from"] = start_from
    if q is not None:
        params["q"] = str(q)
    params.update(extra)

    response = _normalize_response(
        vk_method(
            "catalog.getSearchStatuses",
            access_token=access_token,
            proxies=proxies,
            **params,
        )
    )
    return CatalogSearchTopPage(
        response=response,
        next_from=extract_next_from(response),
        method="catalog.getSearchStatuses",
    )


async def get_search_statuses_async(
    *,
    access_token: str,
    count: int = 100,
    start_from: str | None = None,
    q: str | None = None,
    api_version: str = CATALOG_API_VERSION,
    proxies: dict[str, str] | None = None,
    **extra: object,
) -> CatalogSearchTopPage:
    params: dict[str, object] = {
        "count": max(1, int(count)),
        "need_blocks": 1,
        "v": api_version,
    }
    if start_from:
        params["start_from"] = start_from
    if q is not None:
        params["q"] = str(q)
    params.update(extra)

    response = _normalize_response(
        await vk_method_async(
            "catalog.getSearchStatuses",
            access_token=access_token,
            proxies=proxies,
            **params,
        )
    )
    return CatalogSearchTopPage(
        response=response,
        next_from=extract_next_from(response),
        method="catalog.getSearchStatuses",
    )


def get_newsfeed_search(
    *,
    access_token: str,
    count: int = 50,
    start_from: str | None = None,
    q: str | None = None,
    api_version: str = NEWSFEED_API_VERSION,
    proxies: dict[str, str] | None = None,
    **extra: object,
) -> CatalogSearchTopPage:
    """Call ``newsfeed.search`` — wall posts with real ``next_from`` pagination.

    Unlike ``catalog.getSearchStatuses`` (UI catalog, ~15–20 unique posts and a
    non-advancing cursor), this endpoint paginates cleanly and reports
    ``total_count`` in the thousands for typical queries.
    """
    query = str(q).strip() if q is not None else ""
    if not query:
        query = DEFAULT_NEWSFEED_SEARCH_Q
    params: dict[str, object] = {
        "q": query,
        "count": max(1, min(200, int(count))),
        "v": api_version,
    }
    if start_from:
        params["start_from"] = start_from
    params.update(extra)

    response = _normalize_response(
        vk_method(
            "newsfeed.search",
            access_token=access_token,
            proxies=proxies,
            **params,
        )
    )
    return CatalogSearchTopPage(
        response=response,
        next_from=extract_next_from(response),
        method="newsfeed.search",
    )


# Backwards-compatible alias used by older call sites / docs.
get_search_top_async = get_search_statuses_async
