"""Discord voice RTP extension encrypt/decrypt."""

from __future__ import annotations

import os
import struct
import unittest

from allchats_sdk.providers.discord.voice_selfcord import install_discord_rtp_extensions
from allchats_sdk.providers.discord.voice_udp import (
    DiscordVoiceCrypto,
    audio_rtp_extension_payload,
    rtp_header_with_extension,
)


def _header(*, extension: bool = False) -> bytearray:
    header = bytearray(12)
    header[0] = 0x90 if extension else 0x80
    header[1] = 0x78
    struct.pack_into(">H", header, 2, 4)
    struct.pack_into(">I", header, 4, 960)
    struct.pack_into(">I", header, 8, 99)
    return header


class DiscordVoiceCryptoTests(unittest.TestCase):
    def test_aead_roundtrip_strips_extension(self) -> None:
        crypto = DiscordVoiceCrypto(
            mode="aead_aes256_gcm_rtpsize",
            secret_key=os.urandom(32),
        )
        opus = b"\xf8\xff\xfe"
        extension = audio_rtp_extension_payload(1, audio_level=12)
        header = rtp_header_with_extension(bytes(_header()), extension)
        packet = crypto.encrypt(header, extension + opus)
        self.assertEqual(crypto.decrypt(packet), opus)

    def test_aead_roundtrip_without_extension(self) -> None:
        crypto = DiscordVoiceCrypto(
            mode="aead_aes256_gcm_rtpsize",
            secret_key=os.urandom(32),
        )
        opus = b"\xfc\xff\xfe"
        packet = crypto.encrypt(bytes(_header()), opus)
        self.assertEqual(crypto.decrypt(packet), opus)

    def test_outgoing_packet_is_audible_opus(self) -> None:
        crypto = DiscordVoiceCrypto(
            mode="aead_aes256_gcm_rtpsize",
            secret_key=os.urandom(32),
        )

        class Conn:
            dave_session = None
            can_encrypt = False

        class Voice:
            sequence = 8
            timestamp = 960
            ssrc = 15
            mode = "aead_aes256_gcm_rtpsize"
            _connection = Conn()
            _allchats_speaking = True
            _allchats_audio_level = 20

            def _encrypt_aead_aes256_gcm_rtpsize(self, header: bytes, data: bytes) -> bytes:
                return crypto.encrypt(bytes(header), bytes(data))

        voice = Voice()
        install_discord_rtp_extensions(voice)
        opus = b"opus-frame"
        packet = voice._get_voice_packet(opus)
        self.assertTrue(packet[0] & 0x10)
        self.assertEqual(crypto.decrypt(packet), opus)


if __name__ == "__main__":
    unittest.main()
