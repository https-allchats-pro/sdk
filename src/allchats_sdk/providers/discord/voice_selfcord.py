"""Discord voice session backed by discord.py-self VoiceClient.

Replaces the custom voice_ws_worker + owned UDP socket for join/leave/TX/DAVE.
RX still uses our decrypt/decode helpers on packets from VoiceClient's socket listener.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import TYPE_CHECKING, Any

from allchats_sdk.providers.discord.voice_audio_bridge import get_or_create_bridge
from allchats_sdk.providers.discord.voice_udp import (
    FRAME_DURATION_SEC,
    MONO_FRAME_BYTES,
    MONO_FRAME_SAMPLES,
    SAMPLE_RATE,
    CHANNELS,
    DiscordVoiceCrypto,
    mono_pcm_to_stereo,
    stereo_pcm_to_mono,
    _is_silence_pcm,
)

if TYPE_CHECKING:
    from allchats_sdk.providers.discord.manager import DiscordClientManager

logger = logging.getLogger(__name__)


class DiscordSelfcordVoiceSession:
    """Active VoiceClient session with PCM bridge TX/RX."""

    def __init__(
        self,
        *,
        account_id: str,
        manager: DiscordClientManager,
        voice_client: Any,
    ) -> None:
        self.account_id = account_id
        self.manager = manager
        self.voice_client = voice_client
        self._stop = asyncio.Event()
        self._tx_task: asyncio.Task[None] | None = None
        self._pcm_buffer = bytearray()
        self._speaking = False
        self._crypto: DiscordVoiceCrypto | None = None
        self._decoders: dict[int, Any] = {}
        self._loop = asyncio.get_running_loop()
        self._own_ssrc = 0

    def push_pcm(self, mono_pcm: bytes) -> None:
        if not mono_pcm:
            return
        self._pcm_buffer.extend(mono_pcm)

    async def start(self) -> None:
        vc = self.voice_client
        # discord.py-self: wait_until_connected is sync and returns bool.
        connected = bool(vc.wait_until_connected(timeout=30.0))
        if not connected or not vc.is_connected():
            raise RuntimeError("discord VoiceClient failed to connect")

        conn = vc._connection
        self._own_ssrc = int(getattr(conn, "ssrc", 0) or 0)
        from discord.utils import MISSING

        raw_key = vc.secret_key
        raw_mode = vc.mode
        if raw_key is MISSING or not raw_key or raw_mode is MISSING or not raw_mode:
            raise RuntimeError("discord voice crypto is not ready")
        secret_key = bytes(int(item) & 0xFF for item in raw_key)
        mode = str(raw_mode)
        self._crypto = DiscordVoiceCrypto(mode=mode, secret_key=secret_key)

        # send_audio_packet requires an encoder; play() normally creates one.
        try:
            from discord import opus

            if getattr(vc, "encoder", MISSING) is MISSING:
                vc.encoder = opus.Encoder()
        except Exception as exc:
            raise RuntimeError(f"discord opus encoder unavailable: {exc}") from exc

        bridge = get_or_create_bridge(self.account_id, self.manager)
        bridge.bind_transport(self)  # type: ignore[arg-type]
        self.manager.set_voice_transport(self.account_id, self)

        dave_version = int(getattr(conn, "dave_protocol_version", 0) or 0)
        self.manager.update_voice_session(
            self.account_id,
            state="connected",
            endpoint=str(vc.endpoint or ""),
            token=str(getattr(conn, "token", "") or ""),
            session_id=str(vc.session_id or ""),
            mode=mode,
            ssrc=self._own_ssrc,
            dave_protocol_version=dave_version,
            error="",
        )

        conn.add_socket_listener(self._on_udp_packet)
        self._stop.clear()
        self._tx_task = asyncio.create_task(
            self._tx_loop(),
            name=f"discord-selfcord-voice-tx-{self.account_id[:8]}",
        )
        logger.info(
            "discord selfcord voice connected account=%s ssrc=%s mode=%s dave=%s",
            self.account_id[:8],
            self._own_ssrc,
            mode,
            dave_version,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._tx_task is not None and not self._tx_task.done():
            self._tx_task.cancel()
            try:
                await self._tx_task
            except asyncio.CancelledError:
                pass
        self._tx_task = None

        vc = self.voice_client
        conn = getattr(vc, "_connection", None)
        if conn is not None:
            try:
                conn.remove_socket_listener(self._on_udp_packet)
            except Exception:
                pass
        try:
            if vc is not None and vc.is_connected():
                await vc.disconnect(force=True)
        except Exception:
            logger.debug(
                "discord selfcord voice disconnect failed account=%s",
                self.account_id[:8],
                exc_info=True,
            )
        self.manager.clear_voice_transport(self.account_id)

    def _on_udp_packet(self, packet: bytes) -> None:
        # SocketReader runs in a worker thread.
        try:
            self._loop.call_soon_threadsafe(
                lambda: self._loop.create_task(self._handle_udp_packet(packet))
            )
        except RuntimeError:
            pass

    async def _handle_udp_packet(self, packet: bytes) -> None:
        if self._stop.is_set() or self._crypto is None or len(packet) < 12:
            return
        if len(packet) == 74 and packet[0] == 0x02:
            return
        try:
            ssrc = struct.unpack(">I", packet[8:12])[0]
        except struct.error:
            return
        if ssrc == self._own_ssrc:
            return
        payload = self._crypto.decrypt(packet)
        if not payload:
            return
        opus_packet = self._decrypt_dave(ssrc, payload)
        if not opus_packet:
            return
        mono = self._decode_opus(ssrc, opus_packet)
        if not mono:
            return
        bridge = get_or_create_bridge(self.account_id, self.manager)
        await bridge.on_remote_pcm(ssrc, mono)

    def _decrypt_dave(self, ssrc: int, opus_packet: bytes) -> bytes | None:
        if opus_packet == b"\xf8\xff\xfe":
            return opus_packet
        conn = getattr(self.voice_client, "_connection", None)
        version = int(getattr(conn, "dave_protocol_version", 0) or 0) if conn else 0
        if version <= 0:
            return opus_packet
        session = getattr(conn, "dave_session", None) if conn else None
        if session is None or not getattr(session, "ready", False):
            return None
        user_id_raw = self.manager.resolve_voice_ssrc(self.account_id, int(ssrc))
        if not user_id_raw.isdigit():
            return None
        try:
            import davey

            return bytes(session.decrypt(int(user_id_raw), davey.MediaType.audio, opus_packet))
        except Exception:
            try:
                if session.can_passthrough(int(user_id_raw)):
                    return opus_packet
            except Exception:
                pass
            return None

    def _decode_opus(self, ssrc: int, opus_packet: bytes) -> bytes:
        import opuslib

        decoder = self._decoders.get(ssrc)
        if decoder is None:
            decoder = opuslib.Decoder(SAMPLE_RATE, CHANNELS)
            self._decoders[ssrc] = decoder
        for frame_size in (MONO_FRAME_SAMPLES, 1920, 2880, 480, 5760):
            try:
                stereo = decoder.decode(opus_packet, frame_size)
                mono = stereo_pcm_to_mono(stereo)
                if mono:
                    return mono
            except Exception:
                continue
        return b""

    async def _set_speaking(self, speaking: bool) -> None:
        if self._speaking == speaking:
            return
        self._speaking = speaking
        user_id = ""
        client = self.manager.client_for_account(self.account_id)
        if client is not None:
            user_id = client.user_id
        if user_id:
            self.manager.set_user_speaking(
                self.account_id,
                user_id,
                speaking=speaking,
                ssrc=self._own_ssrc or None,
            )
        try:
            import discord

            state = discord.SpeakingState.voice if speaking else discord.SpeakingState.none
            ws = getattr(self.voice_client, "ws", None)
            if ws is not None:
                await ws.speak(state)
        except Exception:
            logger.debug(
                "discord selfcord speaking update failed account=%s",
                self.account_id[:8],
                exc_info=True,
            )

    async def _tx_loop(self) -> None:
        silence = b"\x00" * MONO_FRAME_BYTES
        silence_frames = 0
        while not self._stop.is_set():
            started = asyncio.get_running_loop().time()
            had_pcm = len(self._pcm_buffer) >= MONO_FRAME_BYTES
            if had_pcm:
                frame = bytes(self._pcm_buffer[:MONO_FRAME_BYTES])
                del self._pcm_buffer[:MONO_FRAME_BYTES]
                silence_frames = 0
            else:
                frame = silence
                silence_frames += 1
            is_silence = _is_silence_pcm(frame)
            try:
                if is_silence and not had_pcm:
                    if self._speaking and silence_frames <= 5:
                        await self._send_frame(frame, speaking=True)
                    elif self._speaking:
                        await self._set_speaking(False)
                else:
                    await self._send_frame(frame, speaking=not is_silence)
            except Exception:
                logger.warning(
                    "discord selfcord voice tx failed account=%s",
                    self.account_id[:8],
                    exc_info=silence_frames <= 1,
                )
            elapsed = asyncio.get_running_loop().time() - started
            delay = max(0.0, FRAME_DURATION_SEC - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue

    async def _send_frame(self, mono_pcm: bytes, *, speaking: bool) -> None:
        vc = self.voice_client
        if vc is None or not vc.is_connected():
            return
        conn = getattr(vc, "_connection", None)
        dave_version = int(getattr(conn, "dave_protocol_version", 0) or 0) if conn else 0
        if dave_version > 0 and not bool(getattr(conn, "can_encrypt", False)):
            # Wait for MLS/DAVE readiness before sending (library would send plaintext Opus).
            return
        await self._set_speaking(speaking)
        if len(mono_pcm) < MONO_FRAME_BYTES:
            mono_pcm = mono_pcm + (b"\x00" * (MONO_FRAME_BYTES - len(mono_pcm)))
        stereo = mono_pcm_to_stereo(mono_pcm[:MONO_FRAME_BYTES])
        # Library encodes Opus + DAVE + RTP transport encryption.
        vc.send_audio_packet(stereo, encode=True)


async def start_selfcord_voice_session(
    account_id: str,
    *,
    manager: DiscordClientManager,
    channel_id: str,
) -> DiscordSelfcordVoiceSession:
    import discord
    from discord.voice_state import VoiceConnectionState

    library_client = manager.discord_library_client(account_id)
    if library_client is None:
        raise RuntimeError("discord client is not connected")

    channel = library_client.get_channel(int(channel_id))
    if channel is None:
        channel = await library_client.fetch_channel(int(channel_id))
    if not isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        raise RuntimeError("channel is not a voice channel")

    # Leave any existing VoiceClient for this guild first.
    existing = channel.guild.voice_client if channel.guild is not None else None
    if existing is not None and existing.is_connected():
        await existing.disconnect(force=True)

    async def voice_ws_hook(_ws: Any, message: dict[str, Any]) -> None:
        if not isinstance(message, dict):
            return
        op = int(message.get("op") or -1)
        data = message.get("d") if isinstance(message.get("d"), dict) else {}
        if op == 5:  # Speaking
            speaking = bool(int(data.get("speaking") or 0))
            speaker_id = str(data.get("user_id") or "").strip()
            ssrc = data.get("ssrc")
            ssrc_int = int(ssrc) if ssrc is not None else None
            if not speaker_id and ssrc_int is not None:
                speaker_id = manager.resolve_voice_ssrc(account_id, ssrc_int)
            if speaker_id:
                manager.set_user_speaking(
                    account_id,
                    speaker_id,
                    speaking=speaking,
                    ssrc=ssrc_int,
                )
            return
        if op in {11, 12}:  # Clients connect / platform
            users = data.get("users") if isinstance(data.get("users"), list) else []
            if not users and isinstance(data.get("user_ids"), list):
                for raw_id in data.get("user_ids") or []:
                    text = str(raw_id or "").strip()
                    if text:
                        manager.set_user_speaking(account_id, text, speaking=False)
                return
            for item in users:
                if not isinstance(item, dict):
                    continue
                connected_user = str(item.get("user_id") or "").strip()
                audio_ssrc = item.get("audio_ssrc") or item.get("ssrc")
                if connected_user and audio_ssrc is not None:
                    manager.set_user_speaking(
                        account_id,
                        connected_user,
                        speaking=False,
                        ssrc=int(audio_ssrc),
                    )

    class OmniVoiceClient(discord.VoiceClient):
        def create_connection_state(self) -> VoiceConnectionState:
            return VoiceConnectionState(self, hook=voice_ws_hook)

    voice_client = await channel.connect(
        cls=OmniVoiceClient,
        self_deaf=False,
        self_mute=False,
        reconnect=True,
        timeout=30.0,
    )
    session = DiscordSelfcordVoiceSession(
        account_id=account_id,
        manager=manager,
        voice_client=voice_client,
    )
    try:
        await session.start()
    except Exception:
        try:
            await session.stop()
        except Exception:
            pass
        raise
    return session
