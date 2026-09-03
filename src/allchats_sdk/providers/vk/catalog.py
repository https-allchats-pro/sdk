"""VK catalog helpers for search / statuses via ``vk_method``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from allchats_sdk.providers.vk.native_api import vk_method, vk_method_async

# Browser search/catalog UI uses a newer API version than messaging defaults.
CATALOG_API_VERSION = "5.288"


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
    """Pull pagination cursor from known catalog response shapes."""
    if not isinstance(payload, dict):
        return None

    for key in ("next_from", "nextFrom", "start_from"):
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
                            found = _as_optional_str(block.get("next_from"))
                            if found:
                                return found
                    for block in blocks:
                        if isinstance(block, dict):
                            found = _as_optional_str(block.get("next_from"))
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


# Backwards-compatible alias used by older call sites / docs.
get_search_top_async = get_search_statuses_async
