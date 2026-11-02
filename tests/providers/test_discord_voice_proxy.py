"""Discord voice UDP proxy eligibility tests."""

from __future__ import annotations

import unittest

import asyncio

from allchats_sdk.providers.discord.voice_selfcord import (
    install_direct_discord_voice_websocket,
    is_discord_voice_ws_url,
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

    def test_http_vpn_cannot_carry_udp(self) -> None:
        self.assertTrue(voice_udp_requires_socks5("http://10.0.0.1:8080"))
        self.assertTrue(voice_udp_requires_socks5("https://10.0.0.1:8443"))
        self.assertTrue(voice_udp_requires_socks5("socks4://10.0.0.1:1080"))

    def test_voice_ws_host(self) -> None:
        self.assertTrue(is_discord_voice_ws_url("wss://c-fra16.discord.media:443/?v=9"))
        self.assertFalse(is_discord_voice_ws_url("wss://gateway.discord.gg/?v=9&encoding=json"))

    def test_http_proxy_voice_ws_goes_direct(self) -> None:
        class Http:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict]] = []

            async def ws_connect(self, url: str, **kwargs):
                self.calls.append((url, kwargs))
                return "ok"

        http = Http()
        install_direct_discord_voice_websocket(http)
        install_direct_discord_voice_websocket(http)

        async def run() -> None:
            await http.ws_connect("wss://c-fra16.discord.media/?v=9", proxy="http://10.0.0.1:8080")
            await http.ws_connect("wss://gateway.discord.gg/?v=9", proxy="http://10.0.0.1:8080")

        asyncio.run(run())
        self.assertEqual(http.calls[0][1]["proxy"], None)
        self.assertIsNone(http.calls[0][1]["proxy_auth"])
        self.assertEqual(http.calls[1][1]["proxy"], "http://10.0.0.1:8080")
        self.assertNotIn("proxy_auth", http.calls[1][1])


if __name__ == "__main__":
    unittest.main()
