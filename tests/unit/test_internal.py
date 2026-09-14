"""internal/ package layout and legacy shims."""

from __future__ import annotations

import unittest

from allchats_sdk.internal.registry import ProviderRegistry, default_registry
from allchats_sdk.internal.observability import configure_metrics, record_auth
from allchats_sdk.internal.runtime.register import register_builtin_providers


class InternalPackageTests(unittest.TestCase):
    def test_registry_lives_under_internal(self) -> None:
        self.assertIsInstance(default_registry, ProviderRegistry)

    def test_legacy_registry_shim(self) -> None:
        from allchats_sdk import registry as legacy

        self.assertIs(legacy.default_registry, default_registry)
        self.assertIs(legacy.ProviderRegistry, ProviderRegistry)

    def test_legacy_observability_shim_follows_configure(self) -> None:
        calls: list[str] = []

        def _auth(*_a, **_k) -> None:
            calls.append("auth")

        configure_metrics(auth=_auth)
        from allchats_sdk import observability as legacy

        legacy.record_auth("telegram", "ok")
        self.assertEqual(calls, ["auth"])
        # restore noop for other tests
        configure_metrics(auth=lambda *_a, **_k: None)

    def test_register_shim(self) -> None:
        from allchats_sdk.providers import register as legacy_register

        self.assertIs(
            legacy_register.register_builtin_providers,
            register_builtin_providers,
        )


if __name__ == "__main__":
    unittest.main()
