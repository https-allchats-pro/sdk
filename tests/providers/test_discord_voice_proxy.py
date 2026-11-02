"""Discord voice UDP proxy eligibility tests."""

from __future__ import annotations

import unittest

from allchats_sdk.providers.discord.voice_selfcord import (
    voice_udp_proxy_scheme,
    voice_udp_requires_socks5,
)


class DiscordVoiceProxyTests(unittest.TestCase):
    def test_direct_udp_is_allowed(self) -> None:
        self.assertEqual(voice_udp_proxy_scheme(None), "")
        self.assertFalse(voice_udp_requires_socks5(None))
        self.assertFalse(voice_udp_requires_socks5(""))

    def test_socks5_is_allowed(self) -> None:
        self.assertFalse(voice_udp_requires_socks5("socks5://user:pass@10.0.0.1:1080"))
        self.assertFalse(voice_udp_requires_socks5("socks5h://10.0.0.1:1080"))

    def test_http_vpn_is_rejected(self) -> None:
        self.assertTrue(voice_udp_requires_socks5("http://10.0.0.1:8080"))
        self.assertTrue(voice_udp_requires_socks5("https://10.0.0.1:8443"))
        self.assertTrue(voice_udp_requires_socks5("socks4://10.0.0.1:1080"))


if __name__ == "__main__":
    unittest.main()
