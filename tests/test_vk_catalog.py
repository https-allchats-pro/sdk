"""Unit tests for VK catalog helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from allchats_sdk.providers.vk.catalog import (
    CATALOG_API_VERSION,
    extract_next_from,
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


if __name__ == "__main__":
    unittest.main()
