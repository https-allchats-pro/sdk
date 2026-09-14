"""MAX user helper tests."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from allchats_sdk.providers.max.users import max_user_display_name


class MaxUserDisplayNameTests(unittest.TestCase):
    def test_prefers_full_name(self) -> None:
        user = SimpleNamespace(
            names=[SimpleNamespace(name="Alice Example", first_name="", last_name="")]
        )
        self.assertEqual(max_user_display_name(user), "Alice Example")

    def test_falls_back_to_first_last(self) -> None:
        user = SimpleNamespace(
            names=[SimpleNamespace(name="", first_name="Alice", last_name="Example")]
        )
        self.assertEqual(max_user_display_name(user), "Alice Example")

    def test_returns_none_when_empty(self) -> None:
        user = SimpleNamespace(names=[])
        self.assertIsNone(max_user_display_name(user))


if __name__ == "__main__":
    unittest.main()
