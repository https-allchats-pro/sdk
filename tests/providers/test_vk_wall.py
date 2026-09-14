"""VK wall / group helpers and native API error tests."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from allchats_sdk.providers.vk.native_api import VkNativeApiError, vk_method
from allchats_sdk.providers.vk.wall import (
    VkGroup,
    normalize_group_ref,
    resolve_group,
    iter_wall_posts_sync,
)


class VkNativeApiErrorTests(unittest.TestCase):
    def test_rate_limit_property(self) -> None:
        self.assertTrue(VkNativeApiError("too many", error_code=6).is_rate_limit)
        self.assertTrue(VkNativeApiError("rate", error_code=29).is_rate_limit)
        self.assertFalse(VkNativeApiError("denied", error_code=15).is_rate_limit)


class NormalizeGroupRefTests(unittest.TestCase):
    def test_screen_name_and_ids(self) -> None:
        self.assertEqual(normalize_group_ref("vc_ru"), "vc_ru")
        self.assertEqual(normalize_group_ref(123), "123")
        self.assertEqual(normalize_group_ref(-456), "456")
        self.assertEqual(normalize_group_ref("-789"), "789")
        self.assertEqual(normalize_group_ref("club42"), "42")
        self.assertEqual(normalize_group_ref("public99"), "99")

    def test_url(self) -> None:
        self.assertEqual(normalize_group_ref("https://vk.com/vc_ru"), "vc_ru")
        self.assertEqual(normalize_group_ref("https://vk.ru/club1"), "1")


class ResolveGroupTests(unittest.TestCase):
    @patch("allchats_sdk.providers.vk.wall.vk_method")
    def test_resolve_from_list_response(self, mock_method: object) -> None:
        mock_method.return_value = [  # type: ignore[attr-defined]
            {"id": 10, "name": "VC", "screen_name": "vc_ru"}
        ]
        group = resolve_group("vc_ru", access_token="tok")
        self.assertEqual(group, VkGroup(id=10, name="VC", screen_name="vc_ru"))
        self.assertEqual(group.owner_id, -10)
        mock_method.assert_called_once()  # type: ignore[attr-defined]
        kwargs = mock_method.call_args.kwargs  # type: ignore[attr-defined]
        self.assertEqual(kwargs["group_ids"], "vc_ru")

    @patch("allchats_sdk.providers.vk.wall.vk_method")
    def test_resolve_from_wrapped_response(self, mock_method: object) -> None:
        mock_method.return_value = {  # type: ignore[attr-defined]
            "groups": [{"id": 5, "name": "VK", "screen_name": "vk"}]
        }
        group = resolve_group("vk", access_token="tok")
        self.assertEqual(group.id, 5)
        self.assertEqual(group.screen_name, "vk")

    @patch("allchats_sdk.providers.vk.wall.vk_method")
    def test_resolve_missing(self, mock_method: object) -> None:
        mock_method.return_value = []  # type: ignore[attr-defined]
        with self.assertRaises(VkNativeApiError):
            resolve_group("missing", access_token="tok")


class IterWallPostsTests(unittest.TestCase):
    @patch("allchats_sdk.providers.vk.wall.vk_method")
    def test_pagination_and_since_cutoff(self, mock_method: object) -> None:
        group = VkGroup(id=100, name="Test", screen_name="test")
        # page 1: two posts; page 2: one older than since
        mock_method.side_effect = [  # type: ignore[attr-defined]
            {
                "items": [
                    {"id": 3, "owner_id": -100, "date": 1_700_000_200, "text": "new"},
                    {"id": 2, "owner_id": -100, "date": 1_700_000_100, "text": "mid"},
                ]
            },
            {
                "items": [
                    {"id": 1, "owner_id": -100, "date": 1_600_000_000, "text": "old"},
                ]
            },
        ]
        since = datetime.fromtimestamp(1_700_000_050, tz=UTC)
        posts = list(
            iter_wall_posts_sync(
                group,
                access_token="tok",
                since=since,
                page_size=2,
            )
        )
        self.assertEqual([p.id for p in posts], [3, 2])
        self.assertEqual(posts[0].url, "https://vk.com/wall-100_3")
        self.assertEqual(mock_method.call_count, 2)  # type: ignore[attr-defined]


class VkMethodRetryTests(unittest.TestCase):
    @patch("allchats_sdk.providers.vk.native_api.time.sleep")
    @patch("allchats_sdk.providers.vk.native_api.requests.post")
    def test_retries_on_rate_limit(self, mock_post: object, mock_sleep: object) -> None:
        rate_limit = type("Resp", (), {})()
        rate_limit.raise_for_status = lambda: None  # type: ignore[attr-defined]
        rate_limit.json = lambda: {  # type: ignore[attr-defined]
            "error": {"error_code": 6, "error_msg": "Too many requests per second"}
        }
        ok = type("Resp", (), {})()
        ok.raise_for_status = lambda: None  # type: ignore[attr-defined]
        ok.json = lambda: {"response": {"ok": True}}  # type: ignore[attr-defined]
        mock_post.side_effect = [rate_limit, ok]  # type: ignore[attr-defined]

        result = vk_method("wall.get", access_token="tok", retries=2, retry_backoff=0.01)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(mock_post.call_count, 2)  # type: ignore[attr-defined]
        mock_sleep.assert_called_once()  # type: ignore[attr-defined]

    @patch("allchats_sdk.providers.vk.native_api.time.sleep")
    @patch("allchats_sdk.providers.vk.native_api.requests.post")
    def test_non_rate_limit_not_retried(self, mock_post: object, mock_sleep: object) -> None:
        resp = type("Resp", (), {})()
        resp.raise_for_status = lambda: None  # type: ignore[attr-defined]
        resp.json = lambda: {  # type: ignore[attr-defined]
            "error": {"error_code": 15, "error_msg": "Access denied"}
        }
        mock_post.return_value = resp  # type: ignore[attr-defined]

        with self.assertRaises(VkNativeApiError) as ctx:
            vk_method("wall.get", access_token="tok", retries=3)
        self.assertEqual(ctx.exception.error_code, 15)
        self.assertEqual(mock_post.call_count, 1)  # type: ignore[attr-defined]
        mock_sleep.assert_not_called()  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()
