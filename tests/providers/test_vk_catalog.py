"""Unit tests for VK catalog helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from allchats_sdk.providers.vk.catalog import (
    CATALOG_API_VERSION,
    extract_next_from,
    get_newsfeed_search,
    get_search_statuses,
    get_search_top,
)


class ExtractNextFromTests(unittest.TestCase):
    def test_top_level(self) -> None:
        self.assertEqual(extract_next_from({"next_from": "abc"}), "abc")

    def test_newsfeed_block_cursor(self) -> None:
        payload = {
            "catalog": {
                "sections": [
                    {
                        "blocks": [
                            {"data_type": "none"},
                            {
                                "data_type": "newsfeed_items",
                                "next_from": "search_feed~page2",
                            },
                        ]
                    }
                ]
            }
        }
        self.assertEqual(extract_next_from(payload), "search_feed~page2")

    def test_missing(self) -> None:
        self.assertIsNone(extract_next_from({"items": []}))

    def test_ignores_echoed_start_from(self) -> None:
        # VK may echo the request cursor as start_from; that must not win over next_from.
        payload = {
            "start_from": "search_feed~page1",
            "catalog": {
                "sections": [
                    {
                        "blocks": [
                            {
                                "data_type": "newsfeed_items",
                                "next_from": "search_feed~page2",
                            },
                        ]
                    }
                ]
            },
        }
        self.assertEqual(extract_next_from(payload), "search_feed~page2")

    def test_start_from_alone_is_not_next_cursor(self) -> None:
        self.assertIsNone(extract_next_from({"start_from": "search_feed~page1"}))


class GetSearchStatusesTests(unittest.TestCase):
    @patch("allchats_sdk.providers.vk.catalog.vk_method")
    def test_calls_statuses_method(self, mock_method: object) -> None:
        mock_method.return_value = {  # type: ignore[attr-defined]
            "newsfeed_items": [],
            "catalog": {
                "sections": [
                    {
                        "blocks": [
                            {"data_type": "newsfeed_items", "next_from": "n1"},
                        ]
                    }
                ]
            },
        }
        page = get_search_statuses(access_token="tok", count=50, start_from="cursor", q="news")
        self.assertEqual(page.next_from, "n1")
        self.assertEqual(page.method, "catalog.getSearchStatuses")
        mock_method.assert_called_once()  # type: ignore[attr-defined]
        args, kwargs = mock_method.call_args  # type: ignore[attr-defined]
        self.assertEqual(args[0], "catalog.getSearchStatuses")
        self.assertEqual(kwargs["access_token"], "tok")
        self.assertEqual(kwargs["count"], 50)
        self.assertEqual(kwargs["start_from"], "cursor")
        self.assertEqual(kwargs["q"], "news")
        self.assertEqual(kwargs["v"], CATALOG_API_VERSION)


class GetSearchTopTests(unittest.TestCase):
    @patch("allchats_sdk.providers.vk.catalog.vk_method")
    def test_calls_top_method(self, mock_method: object) -> None:
        mock_method.return_value = {"catalog": {"sections": []}}  # type: ignore[attr-defined]
        page = get_search_top(access_token="tok", count=10)
        self.assertEqual(page.method, "catalog.getSearchTop")
        args, _kwargs = mock_method.call_args  # type: ignore[attr-defined]
        self.assertEqual(args[0], "catalog.getSearchTop")


class GetNewsfeedSearchTests(unittest.TestCase):
    @patch("allchats_sdk.providers.vk.catalog.vk_method")
    def test_calls_newsfeed_search_and_paginates(self, mock_method: object) -> None:
        mock_method.return_value = {  # type: ignore[attr-defined]
            "count": 1000,
            "total_count": 1000,
            "items": [{"id": 1, "owner_id": -1, "date": 1, "text": "x", "post_type": "post"}],
            "next_from": "50/-1_1",
        }
        page = get_newsfeed_search(
            access_token="tok",
            count=50,
            start_from="0/-1_0",
            q="читать продолжение",
        )
        self.assertEqual(page.method, "newsfeed.search")
        self.assertEqual(page.next_from, "50/-1_1")
        args, kwargs = mock_method.call_args  # type: ignore[attr-defined]
        self.assertEqual(args[0], "newsfeed.search")
        self.assertEqual(kwargs["q"], "читать продолжение")
        self.assertEqual(kwargs["count"], 50)
        self.assertEqual(kwargs["start_from"], "0/-1_0")

    @patch("allchats_sdk.providers.vk.catalog.vk_method")
    def test_empty_query_uses_default_space(self, mock_method: object) -> None:
        mock_method.return_value = {"items": [], "next_from": None}  # type: ignore[attr-defined]
        get_newsfeed_search(access_token="tok", q=None)
        _args, kwargs = mock_method.call_args  # type: ignore[attr-defined]
        self.assertEqual(kwargs["q"], " ")


if __name__ == "__main__":
    unittest.main()
