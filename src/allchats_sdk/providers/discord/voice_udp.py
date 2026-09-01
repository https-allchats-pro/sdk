from __future__ import annotations

import array
import asyncio
import logging
import socket
import struct
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

SAMPLE_RATE = 48000
CHANNELS = 2
# Discord voice uses 20ms Opus frames (960 samples @ 48kHz).
MONO_FRAME_SAMPLES = 960
MONO_FRAME_BYTES = MONO_FRAME_SAMPLES * 2
FRAME_DURATION_SEC = 0.02
RTP_VERSION = 2
RTP_PAYLOAD_TYPE = 0x78

PREFERRED_MODES = (
    "aead_aes256_gcm_rtpsize",
    "aead_xchacha20_poly1305_rtpsize",
)

# Peak absolute sample below this counts as silence (s16le).
_SILENCE_PEAK = 180


def _is_silence_pcm(mono: bytes) -> bool:
    if not mono or not any(mono):
        return True
    samples = array.array("h")
    samples.frombytes(mono[: len(mono) - (len(mono) % 2)])
    peak = 0
    for sample in samples:
        abs_sample = -sample if sample < 0 else sample
        if abs_sample > peak:
            peak = abs_sample
            if peak >= _SILENCE_PEAK:
                return False
    return True


def pick_encryption_mode(modes: list[Any] | None) -> str:
    available = {str(item) for item in (modes or [])}
    for mode in PREFERRED_MODES:
        if mode in available:
            return mode
    if "aead_xchacha20_poly1305_rtpsize" in available:
        return "aead_xchacha20_poly1305_rtpsize"
    raise RuntimeError(f"no supported Discord voice encryption mode in {sorted(available)}")


def mono_pcm_to_stereo(mono: bytes) -> bytes:
    if len(mono) < 2:
        return b""
    samples = array.array("h")
    samples.frombytes(mono[: len(mono) - (len(mono) % 2)])
    stereo = array.array("h")
    for sample in samples:
        stereo.append(sample)
        stereo.append(sample)
    return stereo.tobytes()


def stereo_pcm_to_mono(stereo: bytes) -> bytes:
    if len(stereo) < 4:
        return b""
    samples = array.array("h")
    samples.frombytes(stereo[: len(stereo) - (len(stereo) % 4)])
    mono = array.array("h")
    for i in range(0, len(samples) - 1, 2):
        mixed = (int(samples[i]) + int(samples[i + 1])) // 2
        if mixed > 32767:
            mixed = 32767
        elif mixed < -32768:
            mixed = -32768
        mono.append(mixed)
    return mono.tobytes()


def mix_mono_frames(frames: list[bytes]) -> bytes:
    if not frames:
        return b"\x00" * MONO_FRAME_BYTES
    length = MONO_FRAME_BYTES
    accum = [0] * (length // 2)
    for frame in frames:
        raw = frame
        if len(raw) < length:
            raw = raw + (b"\x00" * (length - len(raw)))
        samples = array.array("h")
        samples.frombytes(raw[:length])
        for i, sample in enumerate(samples):
            accum[i] += int(sample)
    out = array.array("h")
    for value in accum:
        if value > 32767:
            value = 32767
        elif value < -32768:
            value = -32768
        out.append(value)
    return out.tobytes()


class DiscordVoiceCrypto:
    def __init__(self, *, mode: str, secret_key: bytes) -> None:
        self.mode = mode
        self.secret_key = bytes(secret_key)
        self._nonce_counter = 0
        if mode == "aead_aes256_gcm_rtpsize":
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            self._aesgcm = AESGCM(self.secret_key)
            self._nacl = None
        elif mode == "aead_xchacha20_poly1305_rtpsize":
            from nacl.bindings import (
                crypto_aead_xchacha20poly1305_ietf_decrypt,
                crypto_aead_xchacha20poly1305_ietf_encrypt,
            )

            self._aesgcm = None
            self._encrypt = crypto_aead_xchacha20poly1305_ietf_encrypt
            self._decrypt = crypto_aead_xchacha20poly1305_ietf_decrypt
        else:
            raise RuntimeError(f"unsupported voice mode: {mode}")

    def _next_nonce_bytes(self) -> bytes:
        self._nonce_counter = (self._nonce_counter + 1) & 0xFFFFFFFF
        return struct.pack(">I", self._nonce_counter)

    def encrypt(self, rtp_header: bytes, opus_packet: bytes) -> bytes:
        nonce_suffix = self._next_nonce_bytes()
        if self.mode == "aead_aes256_gcm_rtpsize":
            assert self._aesgcm is not None
            nonce = nonce_suffix + (b"\x00" * 8)
            encrypted = self._aesgcm.encrypt(nonce, opus_packet, rtp_header)
            return rtp_header + encrypted + nonce_suffix
        nonce = nonce_suffix + (b"\x00" * 20)
        encrypted = self._encrypt(opus_packet, rtp_header, nonce, self.secret_key)
        return rtp_header + encrypted + nonce_suffix

    def decrypt(self, packet: bytes) -> bytes | None:
        if len(packet) < 12 + 16 + 4:
            return None
        # RTP header may include extension.
        header_size = 12
        if packet[0] & 0x10:
            if len(packet) < 16:
                return None
            ext_len = struct.unpack(">H", packet[14:16])[0]
            header_size = 16 + ext_len * 4
        if len(packet) < header_size + 16 + 4:
            return None
        header = packet[:header_size]
        nonce_suffix = packet[-4:]
        body = packet[header_size:-4]
        try:
            if self.mode == "aead_aes256_gcm_rtpsize":
                assert self._aesgcm is not None
                nonce = nonce_suffix + (b"\x00" * 8)
                return self._aesgcm.decrypt(nonce, body, header)
            nonce = nonce_suffix + (b"\x00" * 20)
            return self._decrypt(body, header, nonce, self.secret_key)
        except Exception:
            return None


class DiscordVoiceUdpTransport:
    def __init__(
        self,
        *,
        account_id: str,
        server_ip: str,
        server_port: int,
        ssrc: int,
        mode: str,
        secret_key: bytes,
        on_decoded_pcm: Callable[[int, bytes], Awaitable[None] | None],
        speak_callback: Callable[[bool], Awaitable[None] | None] | None = None,
        dave_session: Any | None = None,
        dave_protocol_version: int = 0,
        resolve_user_id: Callable[[int], str] | None = None,
    ) -> None:
        self.account_id = account_id
        self.server_ip = server_ip
        self.server_port = server_port
        self.ssrc = int(ssrc)
        self.crypto = DiscordVoiceCrypto(mode=mode, secret_key=secret_key)
        self.on_decoded_pcm = on_decoded_pcm
        self.speak_callback = speak_callback
        self.dave_session = dave_session
        self.dave_protocol_version = int(dave_protocol_version or 0)
        self.resolve_user_id = resolve_user_id
        self._sock: socket.socket | None = None
        self._stop = asyncio.Event()
        self._rx_task: asyncio.Task[None] | None = None
        self._tx_task: asyncio.Task[None] | None = None
        self._sequence = 0
        self._timestamp = 0
        self._pcm_buffer = bytearray()
        self._speaking = False
        self._ssrc_announced = False
        self._encoder = None
        self._decoders: dict[int, Any] = {}
        self._dave_skip_logged = False

    def bind_socket(self, sock: socket.socket) -> None:
        self._sock = sock
        self._sock.setblocking(False)

    def set_dave_session(self, dave_session: Any | None) -> None:
        # Accept either DiscordDaveSession wrapper or raw davey session.
        self.dave_session = dave_session
        if dave_session is not None:
            try:
                version = int(getattr(dave_session, "protocol_version", 0) or 0)
            except Exception:
                version = 0
            if version > 0:
                self.dave_protocol_version = version
            self._dave_skip_logged = False

    def set_dave_protocol_version(self, version: int) -> None:
        self.dave_protocol_version = max(0, int(version or 0))

    def _raw_dave_session(self) -> Any | None:
        session = self.dave_session
        if session is None:
            return None
        # DiscordDaveSession wrapper exposes .session
        inner = getattr(session, "session", None)
        if inner is not None and hasattr(session, "ready") and hasattr(session, "protocol_version"):
            return inner
        return session

    def _effective_dave_version(self) -> int:
        version = int(self.dave_protocol_version or 0)
        outer = self.dave_session
        if outer is not None:
            try:
                version = max(version, int(getattr(outer, "protocol_version", 0) or 0))
            except Exception:
                pass
        session = self._raw_dave_session()
        if session is not None:
            try:
                version = max(version, int(getattr(session, "protocol_version", 0) or 0))
            except Exception:
                pass
        return version

    def _dave_ready(self) -> bool:
        outer = self.dave_session
        if outer is not None and hasattr(outer, "ready") and hasattr(outer, "session"):
            try:
                return bool(outer.ready)
            except Exception:
                pass
        session = self._raw_dave_session()
        return bool(session is not None and getattr(session, "ready", False))

    def _log_dave_skip(self, reason: str) -> None:
        if self._dave_skip_logged:
            return
        self._dave_skip_logged = True
        logger.warning(
            "discord dave media skipped account=%s reason=%s version=%s ready=%s",
            self.account_id[:8],
            reason,
            self._effective_dave_version(),
            self._dave_ready(),
        )

    async def start(self) -> None:
        import opuslib

        self._encoder = opuslib.Encoder(SAMPLE_RATE, CHANNELS, opuslib.APPLICATION_VOIP)
        # opuslib bitrate ctl is broken on some macOS/arm64 libopus builds (EINVAL).
        try:
            self._encoder.bitrate = 64000
        except Exception:
            pass
        self._stop.clear()
        if self._sock is None:
            raise RuntimeError("udp socket is not bound")
        # Discord requires a Speaking opcode before any RTP (registers SSRC).
        await self._force_speaking(False)
        loop = asyncio.get_running_loop()
        self._rx_task = asyncio.create_task(self._rx_loop(loop), name=f"discord-udp-rx-{self.account_id[:8]}")
        self._tx_task = asyncio.create_task(self._tx_loop(), name=f"discord-udp-tx-{self.account_id[:8]}")

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._rx_task, self._tx_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._rx_task = None
        self._tx_task = None
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        await self._set_speaking(False)

    def push_pcm(self, mono_pcm: bytes) -> None:
        if not mono_pcm:
            return
        self._pcm_buffer.extend(mono_pcm)

    async def _force_speaking(self, speaking: bool) -> None:
        self._speaking = speaking
        self._ssrc_announced = True
        if self.speak_callback is None:
            return
        try:
            result = self.speak_callback(speaking)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning(
                "discord voice speaking op failed account=%s err=%r",
                self.account_id[:8],
                exc,
            )

    async def _set_speaking(self, speaking: bool) -> None:
        if self._speaking == speaking and self._ssrc_announced:
            return
        await self._force_speaking(speaking)

    def _build_rtp_header(self) -> bytes:
        self._sequence = (self._sequence + 1) & 0xFFFF
        header = bytearray(12)
        header[0] = 0x80
        header[1] = RTP_PAYLOAD_TYPE
        struct.pack_into(">H", header, 2, self._sequence)
        struct.pack_into(">I", header, 4, self._timestamp & 0xFFFFFFFF)
        struct.pack_into(">I", header, 8, self.ssrc)
        self._timestamp = (self._timestamp + MONO_FRAME_SAMPLES) & 0xFFFFFFFF
        return bytes(header)

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
                    # Keep a short silence tail after speech, then stop RTP.
                    if self._speaking and silence_frames <= 5:
                        await self._send_frame(frame, speaking=True)
                    elif self._speaking:
                        await self._set_speaking(False)
                    # else: idle, SSRC already announced
                else:
                    await self._send_frame(frame, speaking=not is_silence)
            except Exception as exc:
                logger.warning(
                    "discord voice tx failed account=%s err_type=%s err=%r",
                    self.account_id[:8],
                    type(exc).__name__,
                    exc,
                    exc_info=silence_frames <= 1,
                )
            elapsed = asyncio.get_running_loop().time() - started
            delay = max(0.0, FRAME_DURATION_SEC - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue

    def _encrypt_opus_payload(self, opus_packet: bytes) -> bytes | None:
        # Mirror davey: encrypt only when protocol_version > 0 && session.ready.
        # Never send plaintext Opus on a DAVE call — Discord peers cannot hear it.
        if self._effective_dave_version() <= 0:
            return opus_packet
        if not self._dave_ready():
            self._log_dave_skip("encrypt_not_ready")
            return None
        session = self._raw_dave_session()
        if session is None:
            self._log_dave_skip("encrypt_no_session")
            return None
        try:
            encrypted = bytes(session.encrypt_opus(opus_packet))
            self._dave_skip_logged = False
            return encrypted
        except Exception as exc:
            logger.warning(
                "discord dave encrypt failed account=%s err=%r ready=%s",
                self.account_id[:8],
                exc,
                self._dave_ready(),
            )
            return None

    def _decrypt_opus_payload(self, ssrc: int, opus_packet: bytes) -> bytes | None:
        # Discord silence packet — never DAVE-encrypted.
        if opus_packet == b"\xf8\xff\xfe":
            return opus_packet
        if self._effective_dave_version() <= 0:
            return opus_packet
        if not self._dave_ready():
            self._log_dave_skip("decrypt_not_ready")
            return None
        session = self._raw_dave_session()
        if session is None:
            self._log_dave_skip("decrypt_no_session")
            return None
        if self.resolve_user_id is None:
            self._log_dave_skip("decrypt_no_resolver")
            return None
        user_id_raw = str(self.resolve_user_id(ssrc) or "").strip()
        if not user_id_raw.isdigit():
            self._log_dave_skip(f"decrypt_unknown_ssrc:{ssrc}")
            return None
        user_id = int(user_id_raw)
        try:
            import davey

            decrypted = bytes(session.decrypt(user_id, davey.MediaType.audio, opus_packet))
            self._dave_skip_logged = False
            return decrypted
        except Exception:
            try:
                if session.can_passthrough(user_id):
                    return opus_packet
            except Exception:
                pass
            return None

    async def _send_frame(self, mono_pcm: bytes, *, speaking: bool) -> None:
        if self._sock is None or self._encoder is None:
            return
        await self._set_speaking(speaking)
        if len(mono_pcm) < MONO_FRAME_BYTES:
            mono_pcm = mono_pcm + (b"\x00" * (MONO_FRAME_BYTES - len(mono_pcm)))
        stereo = mono_pcm_to_stereo(mono_pcm[:MONO_FRAME_BYTES])
        try:
            opus_packet = self._encoder.encode(stereo, MONO_FRAME_SAMPLES)
        except Exception as exc:
            raise RuntimeError(f"opus encode failed: {exc!r}") from exc
        encrypted_opus = self._encrypt_opus_payload(opus_packet)
        if encrypted_opus is None:
            return
        header = self._build_rtp_header()
        try:
            packet = self.crypto.encrypt(header, encrypted_opus)
        except Exception as exc:
            raise RuntimeError(f"transport encrypt failed: {exc!r}") from exc
        # Prefer sync UDP sendto — asyncio sock_sendto is flaky with this unbound socket.
        try:
            self._sock.sendto(packet, (self.server_ip, int(self.server_port)))
        except BlockingIOError:
            return
        except OSError as exc:
            raise RuntimeError(f"udp sendto failed: {exc!r}") from exc

    async def _rx_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                packet = await asyncio.wait_for(
                    loop.sock_recv(self._sock, 4096),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                if self._stop.is_set():
                    return
                logger.warning(
                    "discord voice rx failed account=%s: %s",
                    self.account_id[:8],
                    exc,
                )
                await asyncio.sleep(0.2)
                continue
            if len(packet) < 12:
                continue
            # Ignore IP discovery responses.
            if len(packet) == 74 and packet[0] == 0x02:
                continue
            try:
                ssrc = struct.unpack(">I", packet[8:12])[0]
            except struct.error:
                continue
            if ssrc == self.ssrc:
                continue
            payload = self.crypto.decrypt(packet)
            if not payload:
                continue
            opus_packet = self._decrypt_opus_payload(ssrc, payload)
            if not opus_packet:
                continue
            mono = self._decode_opus(ssrc, opus_packet)
            if not mono:
                continue
            result = self.on_decoded_pcm(ssrc, mono)
            if asyncio.iscoroutine(result):
                await result

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


def create_udp_socket_and_discover(
    server_ip: str,
    server_port: int,
    ssrc: int,
) -> tuple[socket.socket, str, int]:
    last_error: Exception | None = None
    for attempt in range(3):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(4.0)
        try:
            packet = bytearray(74)
            struct.pack_into(">H", packet, 0, 1)
            struct.pack_into(">H", packet, 2, 70)
            struct.pack_into(">I", packet, 4, ssrc)
            sock.sendto(packet, (server_ip, server_port))
            data, _addr = sock.recvfrom(74)
            if len(data) < 74:
                raise RuntimeError("short udp discovery response")
            ip_raw = data[8:72]
            ip = ip_raw.split(b"\x00", 1)[0].decode("ascii")
            port = struct.unpack(">H", data[72:74])[0]
            if not ip or not port:
                raise RuntimeError("invalid udp discovery payload")
            sock.settimeout(None)
            return sock, ip, port
        except Exception as exc:
            last_error = exc
            try:
                sock.close()
            except Exception:
                pass
            if attempt < 2:
                continue
    raise RuntimeError(f"udp discovery failed: {last_error!r}") from last_error
