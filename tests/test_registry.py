"""Registry tests."""

from __future__ import annotations

import unittest

from allchats_sdk.registry import ProviderRegistry


class ProviderRegistryTests(unittest.TestCase):
    def test_register_and_create(self) -> None:
        registry = ProviderRegistry()

        def _factory(**kwargs):
            return {"kind": "mock", **kwargs}

        registry.register("telegram", _factory)
        created = registry.create("telegram", settings={"x": 1})
        self.assertEqual(created["kind"], "mock")
        self.assertEqual(created["settings"], {"x": 1})

    def test_unknown_provider_raises(self) -> None:
        registry = ProviderRegistry()
        with self.assertRaises(KeyError):
            registry.create("missing")

    def test_available_and_contains(self) -> None:
        registry = ProviderRegistry()
        registry.register("vk", lambda **kwargs: kwargs)
        self.assertEqual(registry.available(), ["vk"])
        self.assertIn("vk", registry)
        self.assertNotIn("telegram", registry)


if __name__ == "__main__":
    unittest.main()
