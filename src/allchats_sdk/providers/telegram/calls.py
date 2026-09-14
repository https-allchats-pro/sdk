from __future__ import annotations

import asyncio
import logging
import os
import random
import struct
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from telethon import events
from telethon.tl.functions.messages import GetDhConfigRequest
from telethon.tl.functions.phone import (
    ConfirmCallRequest,
    DiscardCallRequest,
    RequestCallRequest,
    SendSignalingDataRequest,
)
from telethon.tl.types import (
    InputPhoneCall,
    PhoneCall,
    PhoneCallAccepted,
    PhoneCallDiscardReasonHangup,
    PhoneCallDiscarded,
    PhoneCallProtocol,
    PhoneCallRequested,
    PhoneCallWaiting,
    PhoneConnection,
    PhoneConnectionWebrtc,
    UpdatePhoneCall,
    UpdatePhoneCallSignalingData,
)
from telethon.utils import get_input_user

from allchats_sdk.errors import ValidationError

logger = logging.getLogger(__name__)

AUDIO_SAMPLE_RATE = 48_000
AUDIO_CHANNELS = 1
AUDIO_FRAME_SAMPLES = 480  # 10 ms @ 48 kHz
AUDIO_FRAME_BYTES = AUDIO_FRAME_SAMPLES * 2
_SILENCE_FRAME = bytes(AUDIO_FRAME_BYTES)

MEDIA_TYPE_AUDIO = 0
MEDIA_TYPE_VIDEO = 1
VIDEO_WIDTH = 640
VIDEO_HEIGHT = 480
VIDEO_FPS = 15
VIDEO_FRAME_INTERVAL = 1.0 / VIDEO_FPS
# I420: Y + U/4 + V/4
VIDEO_I420_BYTES = VIDEO_WIDTH * VIDEO_HEIGHT * 3 // 2
VIDEO_HEADER_STRUCT = struct.Struct("<HHHI")  # w, h, rotation, ts_ms
_BLACK_I420 = bytes(VIDEO_I420_BYTES)

# Rolling PCM window for on-demand Whisper (remote + local dialog).
TRANSCRIPT_SECONDS = 25
TRANSCRIPT_MAX_BYTES = AUDIO_SAMPLE_RATE * 2 * TRANSCRIPT_SECONDS
MIN_TRANSCRIPT_BYTES = AUDIO_SAMPLE_RATE * 2  # ~1s

# Live listen-from-button mode: flush on silence (sentence) or max window.
LIVE_MIN_CHUNK_SECONDS = 1.8
LIVE_MAX_CHUNK_SECONDS = 5.0
LIVE_SILENCE_SECONDS = 0.55
LIVE_OVERLAP_SECONDS = 0.25
LIVE_SILENCE_RMS = 350.0
LIVE_POLL_INTERVAL = 0.35
LIVE_MIN_CHUNK_BYTES = int(AUDIO_SAMPLE_RATE * 2 * LIVE_MIN_CHUNK_SECONDS)
LIVE_MAX_CHUNK_BYTES = int(AUDIO_SAMPLE_RATE * 2 * LIVE_MAX_CHUNK_SECONDS)
LIVE_SILENCE_BYTES = int(AUDIO_SAMPLE_RATE * 2 * LIVE_SILENCE_SECONDS)
LIVE_OVERLAP_BYTES = int(AUDIO_SAMPLE_RATE * 2 * LIVE_OVERLAP_SECONDS)
LIVE_BUFFER_MAX_BYTES = int(AUDIO_SAMPLE_RATE * 2 * 30)
RECORDING_MAX_BYTES = int(AUDIO_SAMPLE_RATE * 2 * 7200)  # 2 hours


def _pack_audio_ws_frame(pcm: bytes) -> bytes:
    return bytes([MEDIA_TYPE_AUDIO]) + pcm


def _pack_video_ws_frame(
    width: int,
    height: int,
    rotation: int,
    timestamp_ms: int,
    i420: bytes,
) -> bytes:
    return (
        bytes([MEDIA_TYPE_VIDEO])
        + VIDEO_HEADER_STRUCT.pack(width, height, rotation & 0xFFFF, timestamp_ms & 0xFFFFFFFF)
        + i420
    )


def _parse_video_ws_payload(payload: bytes) -> tuple[int, int, int, int, bytes] | None:
    if len(payload) < VIDEO_HEADER_STRUCT.size:
        return None
    width, height, rotation, timestamp_ms = VIDEO_HEADER_STRUCT.unpack_from(payload, 0)
    i420 = payload[VIDEO_HEADER_STRUCT.size :]
    expected = width * height * 3 // 2
    if width <= 0 or height <= 0 or len(i420) < expected:
        return None
    return width, height, rotation, timestamp_ms, i420[:expected]


def _device_is(device: Any, expected: Any) -> bool:
    if device == expected:
        return True
    name = str(getattr(device, "name", None) or device)
    expected_name = str(getattr(expected, "name", None) or expected)
    return name == expected_name or name.endswith(expected_name)


def _append_ring_pcm(buf: bytearray, pcm: bytes, *, max_bytes: int = TRANSCRIPT_MAX_BYTES) -> None:
    if not pcm:
        return
    buf.extend(pcm)
    overflow = len(buf) - max_bytes
    if overflow > 0:
        del buf[:overflow]


def _mix_pcm_s16le(remote: bytes, local: bytes) -> bytes:
    """Average two mono s16le streams; pad the shorter with silence."""
    length = max(len(remote), len(local))
    length -= length % 2
    if length <= 0:
        return b""
    out = bytearray(length)
    for i in range(0, length, 2):
        r = int.from_bytes(remote[i : i + 2], "little", signed=True) if i + 1 < len(remote) else 0
        l = int.from_bytes(local[i : i + 2], "little", signed=True) if i + 1 < len(local) else 0
        mixed = max(-32768, min(32767, (r + l) // 2))
        out[i : i + 2] = int(mixed).to_bytes(2, "little", signed=True)
    return bytes(out)


def _pcm_s16le_to_wav(pcm: bytes, *, sample_rate: int = AUDIO_SAMPLE_RATE, channels: int = 1) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _pcm_rms_s16le(pcm: bytes) -> float:
    if len(pcm) < 2:
        return 0.0
    total = 0.0
    count = 0
    for i in range(0, len(pcm) - 1, 2):
        sample = int.from_bytes(pcm[i : i + 2], "little", signed=True)
        total += float(sample * sample)
        count += 1
    if count <= 0:
        return 0.0
    return (total / count) ** 0.5


def _looks_like_sentence(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return stripped[-1] in ".?!…;:" or len(stripped.split()) >= 6

_DEFAULT_LIBRARY_VERSIONS = [
    "9.0.0",
    "8.0.0",
    "7.0.0",
    "5.0.0",
    "2.7.7",
    "2.4.4",
]


def _build_call_protocol() -> PhoneCallProtocol:
    library_versions = list(_DEFAULT_LIBRARY_VERSIONS)
    min_layer = 92
    max_layer = 92
    try:
        from ntgcalls import NTgCalls

        protocol = NTgCalls().get_protocol()
        if protocol.library_versions:
            # Keep ntgcalls order as-is — do not reverse.
            library_versions = list(protocol.library_versions)
        min_layer = int(getattr(protocol, "min_layer", min_layer) or min_layer)
        max_layer = int(getattr(protocol, "max_layer", max_layer) or max_layer)
    except Exception:
        logger.debug("ntgcalls protocol unavailable, using default tgcalls versions", exc_info=True)

    return PhoneCallProtocol(
        min_layer=min_layer,
        max_layer=max_layer,
        library_versions=library_versions,
        udp_p2p=True,
        udp_reflector=True,
    )


_CALL_PROTOCOL: PhoneCallProtocol | None = None


def get_call_protocol() -> PhoneCallProtocol:
    global _CALL_PROTOCOL
    if _CALL_PROTOCOL is None:
        _CALL_PROTOCOL = _build_call_protocol()
        logger.info(
            "telegram call protocol layer=%s-%s versions=%s",
            _CALL_PROTOCOL.min_layer,
            _CALL_PROTOCOL.max_layer,
            _CALL_PROTOCOL.library_versions,
        )
    return _CALL_PROTOCOL


def _call_library_versions(phone_call: PhoneCall) -> list[str]:
    # connect_p2p expects OUR supported library versions (ntgcalls), not remote.
    local = list(get_call_protocol().library_versions)
    protocol = getattr(phone_call, "protocol", None)
    remote = list(getattr(protocol, "library_versions", None) or [])
    if not remote:
        return local
    intersection = [version for version in local if version in remote]
    return intersection or local


@dataclass
class _CallSession:
    account_id: str
    call_id: int
    peer: InputPhoneCall
    g_a_hash: bytes
    video: bool
    participant_id: int
    operator_user_id: str
    client: Any = None
    status: str = "ringing"
    direction: str = "outgoing"
    record_call: bool = False
    peer_external_id: str | None = None
    peer_title: str | None = None
    chat_id: str | None = None
    started_at: float = field(default_factory=time.time)
    connected_at: float = 0.0
    audio_ws: Any = None
    media_attached: bool = False
    media_connecting: bool = False
    outbound_task: asyncio.Task[None] | None = None
    outbound_video_task: asyncio.Task[None] | None = None
    inbound_task: asyncio.Task[None] | None = None
    inbound_fifo_path: str | None = None
    audio_buffer: bytearray = field(default_factory=bytearray)
    audio_lock: asyncio.Lock | None = None
    video_lock: asyncio.Lock | None = None
    video_frame: bytes | None = None
    video_frame_meta: tuple[int, int, int, int] | None = None  # w, h, rot, ts
    loop: asyncio.AbstractEventLoop | None = None
    frames_sent: int = 0
    video_frames_sent: int = 0
    frames_received: int = 0
    video_frames_received: int = 0
    frames_forwarded_ws: int = 0
    video_frames_forwarded_ws: int = 0
    operator_bytes_queued: int = 0
    inbound_via_external: bool = False
    transcript_remote: bytearray = field(default_factory=bytearray)
    transcript_local: bytearray = field(default_factory=bytearray)
    recording_remote: bytearray = field(default_factory=bytearray)
    recording_local: bytearray = field(default_factory=bytearray)
    transcript_lock: threading.Lock = field(default_factory=threading.Lock)
    live_transcript_enabled: bool = False
    live_pcm: bytearray = field(default_factory=bytearray)
    live_task: asyncio.Task[None] | None = None
    live_whisper_settings: Any | None = None
    live_busy: bool = False
    live_partial: str = ""


def _build_rtc_servers(phone_call: PhoneCall) -> list[Any]:
    from ntgcalls import RTCServer

    servers: list[Any] = []
    for connection in list(getattr(phone_call, "connections", None) or []):
        try:
            if isinstance(connection, PhoneConnectionWebrtc):
                servers.append(
                    RTCServer(
                        connection.id,
                        connection.ip or "",
                        connection.ipv6 or "",
                        connection.port,
                        connection.username or None,
                        connection.password or None,
                        bool(connection.turn),
                        bool(connection.stun),
                        False,
                    ),
                )
                continue
            if isinstance(connection, PhoneConnection):
                servers.append(
                    RTCServer(
                        connection.id,
                        connection.ip or "",
                        connection.ipv6 or "",
                        connection.port,
                        None,
                        None,
                        True,
                        False,
                        bool(getattr(connection, "tcp", False)),
                        getattr(connection, "peer_tag", None),
                    ),
                )
        except Exception:
            logger.debug(
                "failed to build rtc server from connection=%s",
                type(connection).__name__,
                exc_info=True,
            )
    return servers


class TelegramCallCoordinator:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, int], _CallSession] = {}
        self._registered_clients: set[int] = set()
        self._ntgcalls: Any | None = None
        self._ntgcalls_callbacks_registered = False
        self._call_log_service: Any | None = None
        self._call_recording_service: Any | None = None

    def set_call_log_service(self, service: Any) -> None:
        self._call_log_service = service

    def set_call_recording_service(self, service: Any) -> None:
        self._call_recording_service = service

    def _schedule_call_log(self, coro: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass

    async def _persist_call_event(self, session: _CallSession, *, status: str, **extra: Any) -> None:
        service = self._call_log_service
        if service is None:
            return
        from datetime import UTC, datetime

        started_at = datetime.fromtimestamp(session.started_at, tz=UTC)
        ended_at = extra.get("ended_at")
        duration_sec = extra.get("duration_sec")
        if status in {"ended", "missed", "rejected", "busy", "failed"} and ended_at is None:
            ended_at = datetime.now(UTC)
        if duration_sec is None and session.connected_at:
            duration_sec = max(0, int(time.time() - session.connected_at))
        await service.upsert_event(
            account_id=session.account_id,
            messenger_type="telegram",
            external_call_id=session.call_id,
            direction=session.direction,
            status=status,
            video=session.video,
            chat_id=session.chat_id,
            peer_external_id=session.peer_external_id or str(session.participant_id),
            peer_title=session.peer_title,
            operator_user_id=session.operator_user_id or None,
            started_at=started_at,
            ended_at=ended_at,
            duration_sec=duration_sec,
            record_call=bool(session.record_call),
        )

    def _session_key(self, account_id: str, call_id: int | str) -> tuple[str, int]:
        return account_id, int(call_id)

    async def _await_ntgcalls(self, result: Any, *, timeout: float = 10) -> Any:
        if asyncio.isfuture(result):
            return await asyncio.wait_for(asyncio.wrap_future(result), timeout=timeout)
        return result

    def _get_ntgcalls(self) -> Any | None:
        try:
            from ntgcalls import NTgCalls
        except Exception:
            logger.warning("ntgcalls is not installed; telegram call audio is unavailable")
            return None

        if self._ntgcalls is None:
            self._ntgcalls = NTgCalls()
            self._register_ntgcalls_callbacks()
        return self._ntgcalls

    def _register_ntgcalls_callbacks(self) -> None:
        if self._ntgcalls is None or self._ntgcalls_callbacks_registered:
            return

        coordinator = self

        def _on_signaling(user_id: int, data: bytes) -> None:
            logger.debug(
                "ntgcalls on_signaling participant=%s bytes=%s",
                user_id,
                len(data) if data is not None else 0,
            )
            coordinator._schedule_signaling_outbound(int(user_id), bytes(data or b""))

        def _on_connection_change(user_id: int, network_info: Any) -> None:
            state = getattr(network_info, "state", network_info)
            kind = getattr(network_info, "kind", "")
            logger.info(
                "ntgcalls connection change participant=%s state=%s kind=%s",
                user_id,
                state,
                kind,
            )

        def _on_frames(user_id: int, mode: Any, device: Any, frames: Any) -> None:
            # Do not filter by mode — P2P may deliver under unexpected mode labels.
            frame_list = list(frames or [])
            if frame_list:
                logger.debug(
                    "ntgcalls on_frames participant=%s mode=%s device=%s count=%s",
                    user_id,
                    mode,
                    device,
                    len(frame_list),
                )
            try:
                from ntgcalls import CAMERA, MICROPHONE
            except Exception:
                coordinator._forward_remote_audio(int(user_id), device, frame_list)
                return
            if _device_is(device, CAMERA):
                coordinator._forward_remote_video(int(user_id), device, frame_list)
            elif _device_is(device, MICROPHONE):
                coordinator._forward_remote_audio(int(user_id), device, frame_list)
            else:
                logger.debug(
                    "ntgcalls on_frames ignored device=%s participant=%s",
                    device,
                    user_id,
                )

        def _on_remote_source_change(user_id: int, remote_source: Any) -> None:
            logger.info(
                "ntgcalls remote source change participant=%s device=%s state=%s ssrc=%s",
                user_id,
                getattr(remote_source, "device", None),
                getattr(remote_source, "state", None),
                getattr(remote_source, "ssrc", None),
            )

        self._ntgcalls.on_signaling(_on_signaling)
        self._ntgcalls.on_connection_change(_on_connection_change)
        self._ntgcalls.on_frames(_on_frames)
        self._ntgcalls.on_remote_source_change(_on_remote_source_change)
        self._ntgcalls_callbacks_registered = True

    def _resolve_session_loop(self, session: _CallSession) -> asyncio.AbstractEventLoop | None:
        if session.loop is not None and session.loop.is_running():
            return session.loop
        client_loop = getattr(session.client, "loop", None)
        if client_loop is not None and client_loop.is_running():
            return client_loop
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    def _dispatch_coro(self, session: _CallSession, coro: Any) -> None:
        loop = self._resolve_session_loop(session)
        if loop is None:
            logger.warning(
                "no event loop to dispatch call coroutine account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
            )
            coro.close()
            return

        def _create_task(item: Any = coro) -> None:
            loop.create_task(item)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        try:
            if running is loop:
                loop.create_task(coro)
            else:
                loop.call_soon_threadsafe(_create_task)
        except Exception:
            logger.exception(
                "failed to dispatch call coroutine account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
            )
            try:
                coro.close()
            except Exception:
                pass

    def _schedule_signaling_outbound(self, participant_id: int, data: bytes) -> None:
        for session in self._sessions.values():
            if session.participant_id != participant_id or session.client is None:
                continue
            client = session.client
            peer = session.peer
            account_id = session.account_id
            call_id = session.call_id
            payload = bytes(data)

            async def _send() -> None:
                try:
                    await client(
                        SendSignalingDataRequest(
                            peer=InputPhoneCall(call_id, peer.access_hash),
                            data=payload,
                        ),
                    )
                    logger.info(
                        "telegram call signaling out account=%s call_id=%s bytes=%s",
                        account_id[:8],
                        call_id,
                        len(payload),
                    )
                except Exception:
                    logger.exception(
                        "failed to relay telegram call signaling account=%s call_id=%s",
                        account_id[:8],
                        call_id,
                    )

            self._dispatch_coro(session, _send())
            break

    def _forward_remote_audio(self, participant_id: int, _device: Any, frames: Any) -> None:
        for session in self._sessions.values():
            if session.participant_id != participant_id:
                continue
            for frame in frames or []:
                payload = getattr(frame, "data", None)
                if not payload:
                    continue
                raw = bytes(payload)
                self._record_dialog_pcm(session, raw, remote=True)
                session.frames_received += 1
                peak = 0
                for i in range(0, len(raw) - 1, 2):
                    sample = int.from_bytes(raw[i : i + 2], "little", signed=True)
                    abs_sample = abs(sample)
                    if abs_sample > peak:
                        peak = abs_sample
                if session.frames_received == 1 or session.frames_received % 100 == 0:
                    logger.info(
                        "telegram call on_frames audio account=%s call_id=%s frames=%s bytes=%s peak=%s",
                        session.account_id[:8],
                        session.call_id,
                        session.frames_received,
                        len(raw),
                        peak,
                    )
                self._schedule_ws_send(session, _pack_audio_ws_frame(raw))

    def _forward_remote_video(self, participant_id: int, _device: Any, frames: Any) -> None:
        for session in self._sessions.values():
            if session.participant_id != participant_id or not session.video:
                continue
            for frame in frames or []:
                payload = getattr(frame, "data", None)
                if not payload:
                    continue
                raw = bytes(payload)
                frame_data = getattr(frame, "frame_data", None)
                width = int(getattr(frame_data, "width", 0) or 0)
                height = int(getattr(frame_data, "height", 0) or 0)
                rotation = int(getattr(frame_data, "rotation", 0) or 0)
                timestamp_ms = int(getattr(frame_data, "absolute_capture_timestamp_ms", 0) or 0)
                if width <= 0 or height <= 0:
                    # Infer from I420 size if metadata missing (assume 4:3).
                    # size = w*h*3/2 → w*h = size*2/3
                    pixels = len(raw) * 2 // 3
                    width = VIDEO_WIDTH
                    height = max(1, pixels // width) if width else VIDEO_HEIGHT
                session.video_frames_received += 1
                if session.video_frames_received == 1 or session.video_frames_received % 50 == 0:
                    logger.info(
                        "telegram call on_frames video account=%s call_id=%s frames=%s %sx%s bytes=%s",
                        session.account_id[:8],
                        session.call_id,
                        session.video_frames_received,
                        width,
                        height,
                        len(raw),
                    )
                self._schedule_ws_send(
                    session,
                    _pack_video_ws_frame(width, height, rotation, timestamp_ms, raw),
                )

    def _schedule_ws_send(self, session: _CallSession, payload: bytes) -> None:
        ws = session.audio_ws
        if ws is None:
            return

        async def _send() -> None:
            try:
                await ws.send_bytes(payload)
                if payload and payload[0] == MEDIA_TYPE_VIDEO:
                    session.video_frames_forwarded_ws += 1
                else:
                    session.frames_forwarded_ws += 1
            except Exception:
                logger.warning(
                    "call media ws send failed account=%s call_id=%s",
                    session.account_id[:8],
                    session.call_id,
                    exc_info=True,
                )

        self._dispatch_coro(session, _send())

    def _record_dialog_pcm(self, session: _CallSession, pcm: bytes, *, remote: bool) -> None:
        if not pcm:
            return
        target = session.transcript_remote if remote else session.transcript_local
        recording_target = session.recording_remote if remote else session.recording_local
        with session.transcript_lock:
            _append_ring_pcm(target, pcm)
            if session.record_call:
                _append_ring_pcm(recording_target, pcm, max_bytes=RECORDING_MAX_BYTES)
            if session.live_transcript_enabled and remote:
                _append_ring_pcm(session.live_pcm, pcm, max_bytes=LIVE_BUFFER_MAX_BYTES)

    async def _forward_frame_to_ws(self, session: _CallSession, frame: bytes) -> None:
        self._record_dialog_pcm(session, frame, remote=True)
        ws = session.audio_ws
        if ws is None:
            if session.frames_received == 1 or session.frames_received % 100 == 0:
                logger.warning(
                    "inbound audio without media ws account=%s call_id=%s frames=%s",
                    session.account_id[:8],
                    session.call_id,
                    session.frames_received,
                )
            return
        try:
            await ws.send_bytes(_pack_audio_ws_frame(frame))
            session.frames_forwarded_ws += 1
            if session.frames_forwarded_ws == 1 or session.frames_forwarded_ws % 100 == 0:
                # Peak sample to verify the frame is not pure silence.
                peak = 0
                for i in range(0, len(frame) - 1, 2):
                    sample = int.from_bytes(frame[i : i + 2], "little", signed=True)
                    abs_sample = abs(sample)
                    if abs_sample > peak:
                        peak = abs_sample
                logger.info(
                    "telegram call inbound ws forward account=%s call_id=%s frames=%s peak=%s",
                    session.account_id[:8],
                    session.call_id,
                    session.frames_forwarded_ws,
                    peak,
                )
        except Exception:
            logger.warning(
                "call audio ws send failed account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
                exc_info=True,
            )

    async def _notify_call_status(self, session: _CallSession) -> None:
        ws = session.audio_ws
        if ws is None:
            return
        try:
            await ws.send_json({"type": "status", "status": session.status})
        except Exception:
            logger.debug(
                "failed to notify call status account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
                exc_info=True,
            )

    def register_handlers(self, client: Any, account_id: str) -> None:
        client_key = id(client)
        if client_key in self._registered_clients:
            return
        self._registered_clients.add(client_key)

        @client.on(events.Raw(types=UpdatePhoneCall))
        async def _on_phone_call_update(event: UpdatePhoneCall) -> None:
            try:
                await self._handle_phone_call_update(client, account_id, event.phone_call)
            except Exception:
                logger.exception(
                    "failed to handle telegram phone call update account=%s",
                    account_id[:8],
                )

        @client.on(events.Raw(types=UpdatePhoneCallSignalingData))
        async def _on_phone_call_signaling(event: UpdatePhoneCallSignalingData) -> None:
            try:
                await self._handle_signaling_data(account_id, event.phone_call_id, event.data)
            except Exception:
                logger.exception(
                    "failed to handle telegram call signaling account=%s call_id=%s",
                    account_id[:8],
                    event.phone_call_id,
                )

    async def request_call(
        self,
        client: Any,
        *,
        account_id: str,
        peer: Any,
        video: bool = False,
        record_call: bool = False,
        operator_user_id: str = "",
        chat_id: str | None = None,
        peer_title: str | None = None,
        peer_external_id: str | None = None,
    ) -> dict[str, object]:
        from telethon import utils
        from telethon.tl.types import Channel, Chat, User

        entity = await client.get_entity(peer)
        if isinstance(entity, (Channel, Chat)):
            raise ValidationError("calls are not supported for groups and channels")
        if not isinstance(entity, User):
            raise ValidationError("calls are only supported for private chats")

        participant_id = int(entity.id)
        resolved_peer_external_id = peer_external_id or str(utils.get_peer_id(entity))
        if not peer_title:
            first = str(getattr(entity, "first_name", "") or "").strip()
            last = str(getattr(entity, "last_name", "") or "").strip()
            peer_title = " ".join(part for part in (first, last) if part).strip() or resolved_peer_external_id

        input_user = get_input_user(entity)
        dh = await client(GetDhConfigRequest(version=0, random_length=256))
        g_a_hash = await self._ntgcalls_init_outgoing(participant_id, dh)

        response = await client(
            RequestCallRequest(
                user_id=input_user,
                random_id=random.randint(0, 0x7FFFFFFF),
                g_a_hash=g_a_hash,
                protocol=get_call_protocol(),
                video=video,
            ),
        )
        phone_call = response.phone_call
        if not isinstance(phone_call, PhoneCallWaiting):
            raise ValidationError("failed to start telegram call")

        call_id = int(phone_call.id)
        session = _CallSession(
            account_id=account_id,
            call_id=call_id,
            peer=InputPhoneCall(call_id, phone_call.access_hash),
            g_a_hash=g_a_hash,
            video=video,
            participant_id=participant_id,
            operator_user_id=str(operator_user_id or ""),
            client=client,
            direction="outgoing",
            record_call=bool(record_call),
            peer_external_id=resolved_peer_external_id,
            peer_title=peer_title,
            chat_id=chat_id,
            loop=asyncio.get_running_loop(),
        )
        self._sessions[self._session_key(account_id, call_id)] = session
        self._schedule_call_log(self._persist_call_event(session, status="ringing"))
        logger.info(
            "telegram call requested account=%s call_id=%s video=%s participant=%s",
            account_id[:8],
            call_id,
            video,
            participant_id,
        )
        return {
            "call_id": str(call_id),
            "status": "ringing",
            "video": video,
            "sample_rate": AUDIO_SAMPLE_RATE,
            "channels": AUDIO_CHANNELS,
        }

    async def _ntgcalls_init_outgoing(self, participant_id: int, dh: Any) -> bytes:
        ntgcalls = self._get_ntgcalls()
        if ntgcalls is None:
            raise ValidationError("call audio engine is unavailable")

        from ntgcalls import DhConfig

        try:
            ntgcalls.create_p2p_call(participant_id)
            dh_config = DhConfig(dh.g, dh.p, dh.random)
            g_a_hash = await self._await_ntgcalls(
                ntgcalls.init_exchange(participant_id, dh_config, None),
            )
        except Exception as exc:
            logger.exception(
                "ntgcalls init_exchange failed participant=%s",
                participant_id,
            )
            raise ValidationError("failed to initialize call encryption") from exc

        if not isinstance(g_a_hash, (bytes, bytearray)) or len(g_a_hash) != 32:
            raise ValidationError("failed to initialize call encryption")
        return bytes(g_a_hash)

    async def _ntgcalls_exchange_keys(
        self,
        session: _CallSession,
        g_b: bytes,
    ) -> Any | None:
        ntgcalls = self._get_ntgcalls()
        if ntgcalls is None:
            return None
        try:
            return await self._await_ntgcalls(
                ntgcalls.exchange_keys(session.participant_id, g_b, 0),
            )
        except Exception:
            logger.exception(
                "ntgcalls exchange_keys failed account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
            )
            return None

    def _prepare_inbound_fifo(self, session: _CallSession) -> str:
        path = os.path.join(
            tempfile.gettempdir(),
            f"tgcall-{session.account_id[:8]}-{session.call_id}.pcm",
        )
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        os.mkfifo(path)
        session.inbound_fifo_path = path
        return path

    def _configure_external_streams(self, session: _CallSession) -> None:
        ntgcalls = self._get_ntgcalls()
        if ntgcalls is None:
            return
        from ntgcalls import (
            CAPTURE,
            PLAYBACK,
            EXTERNAL,
            FILE,
            MediaDescription,
            AudioDescription,
            VideoDescription,
        )

        capture_audio = AudioDescription(
            EXTERNAL,
            AUDIO_SAMPLE_RATE,
            AUDIO_CHANNELS,
            "",
            False,
        )
        fifo_path = session.inbound_fifo_path or self._prepare_inbound_fifo(session)
        # FILE sink on PLAYBACK+microphone: ntgcalls only calls
        # enableAudioIncoming() when a Microphone writer exists (not Speaker).
        # P2P also attaches the remote audio track as Device::Microphone.
        playback_audio = AudioDescription(
            FILE,
            AUDIO_SAMPLE_RATE,
            AUDIO_CHANNELS,
            fifo_path,
            True,
        )
        capture_camera = None
        playback_camera = None
        if session.video:
            capture_camera = VideoDescription(
                EXTERNAL,
                VIDEO_WIDTH,
                VIDEO_HEIGHT,
                VIDEO_FPS,
                "",
                False,
            )
            # EXTERNAL writer on PLAYBACK+camera enables enableVideoIncoming().
            playback_camera = VideoDescription(
                EXTERNAL,
                VIDEO_WIDTH,
                VIDEO_HEIGHT,
                VIDEO_FPS,
                "",
                True,
            )
        ntgcalls.set_stream_sources(
            session.participant_id,
            CAPTURE,
            MediaDescription(
                microphone=capture_audio,
                speaker=None,
                camera=capture_camera,
                screen=None,
            ),
        )
        ntgcalls.set_stream_sources(
            session.participant_id,
            PLAYBACK,
            MediaDescription(
                microphone=playback_audio,
                speaker=None,
                camera=playback_camera,
                screen=None,
            ),
        )
        session.inbound_via_external = False
        logger.info(
            "telegram call streams configured participant=%s playback=FILE mic video=%s ntgcalls=%s",
            session.participant_id,
            session.video,
            getattr(__import__("ntgcalls", fromlist=["__version__"]), "__version__", "?"),
        )

    def _start_inbound_fifo_reader(self, session: _CallSession) -> None:
        if session.inbound_task is not None and not session.inbound_task.done():
            return
        path = session.inbound_fifo_path
        if not path:
            return

        async def _loop() -> None:
            import select

            logger.info(
                "telegram call inbound fifo reader starting account=%s call_id=%s path=%s",
                session.account_id[:8],
                session.call_id,
                path,
            )
            fd = -1
            try:
                # Non-blocking open avoids deadlock with ntgcalls writer.
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                logger.info(
                    "telegram call inbound fifo opened account=%s call_id=%s",
                    session.account_id[:8],
                    session.call_id,
                )
                pending = bytearray()
                while session.media_attached or session.media_connecting:
                    readable, _, _ = await asyncio.to_thread(select.select, [fd], [], [], 0.1)
                    if not readable:
                        continue
                    try:
                        chunk = os.read(fd, AUDIO_FRAME_BYTES * 4)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        await asyncio.sleep(0.01)
                        continue
                    pending.extend(chunk)
                    while len(pending) >= AUDIO_FRAME_BYTES:
                        frame = bytes(pending[:AUDIO_FRAME_BYTES])
                        del pending[:AUDIO_FRAME_BYTES]
                        session.frames_received += 1
                        if session.frames_received == 1 or session.frames_received % 100 == 0:
                            logger.info(
                                "telegram call inbound audio account=%s call_id=%s frames=%s",
                                session.account_id[:8],
                                session.call_id,
                                session.frames_received,
                            )
                        await self._forward_frame_to_ws(session, frame)
            except Exception:
                logger.exception(
                    "inbound fifo reader failed account=%s call_id=%s",
                    session.account_id[:8],
                    session.call_id,
                )
            finally:
                if fd >= 0:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                logger.info(
                    "telegram call inbound fifo reader stopped account=%s call_id=%s frames=%s",
                    session.account_id[:8],
                    session.call_id,
                    session.frames_received,
                )

        try:
            session.inbound_task = asyncio.create_task(_loop())
        except RuntimeError:
            session.inbound_task = None

    def _stop_inbound_fifo_reader(self, session: _CallSession) -> None:
        task = session.inbound_task
        session.inbound_task = None
        if task is not None and not task.done():
            task.cancel()
        path = session.inbound_fifo_path
        session.inbound_fifo_path = None
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _start_outbound_audio_loop(self, session: _CallSession) -> None:
        if session.outbound_task is not None and not session.outbound_task.done():
            return
        if session.audio_lock is None:
            session.audio_lock = asyncio.Lock()

        async def _loop() -> None:
            from ntgcalls import FrameData, MICROPHONE

            logger.info(
                "telegram call outbound audio loop started account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
            )
            next_tick = time.perf_counter()
            while session.media_attached:
                ntgcalls = self._get_ntgcalls()
                if ntgcalls is None:
                    break

                frame = _SILENCE_FRAME
                if session.audio_lock is not None:
                    async with session.audio_lock:
                        if len(session.audio_buffer) >= AUDIO_FRAME_BYTES:
                            frame = bytes(session.audio_buffer[:AUDIO_FRAME_BYTES])
                            del session.audio_buffer[:AUDIO_FRAME_BYTES]
                        elif session.audio_buffer:
                            # partial frame — pad with silence
                            frame = bytes(session.audio_buffer) + bytes(
                                AUDIO_FRAME_BYTES - len(session.audio_buffer),
                            )
                            session.audio_buffer.clear()

                timestamp_ms = int(time.monotonic() * 1000)
                try:
                    ntgcalls.send_external_frame(
                        session.participant_id,
                        MICROPHONE,
                        frame,
                        FrameData(timestamp_ms, 0, 0, 0),
                    )
                    self._record_dialog_pcm(session, frame, remote=False)
                    session.frames_sent += 1
                    if session.frames_sent == 1 or session.frames_sent % 500 == 0:
                        logger.info(
                            "telegram call outbound audio account=%s call_id=%s frames=%s queued_bytes=%s",
                            session.account_id[:8],
                            session.call_id,
                            session.frames_sent,
                            session.operator_bytes_queued,
                        )
                except Exception:
                    logger.debug(
                        "outbound audio frame failed account=%s call_id=%s",
                        session.account_id[:8],
                        session.call_id,
                        exc_info=True,
                    )
                    break

                next_tick += 0.01
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    # fell behind — resync clock
                    next_tick = time.perf_counter()
                    await asyncio.sleep(0)

            logger.info(
                "telegram call outbound audio loop stopped account=%s call_id=%s frames=%s",
                session.account_id[:8],
                session.call_id,
                session.frames_sent,
            )

        try:
            session.outbound_task = asyncio.create_task(_loop())
        except RuntimeError:
            session.outbound_task = None

    def _stop_outbound_audio_loop(self, session: _CallSession) -> None:
        task = session.outbound_task
        session.outbound_task = None
        if task is not None and not task.done():
            task.cancel()

    def _start_outbound_video_loop(self, session: _CallSession) -> None:
        if not session.video:
            return
        if session.outbound_video_task is not None and not session.outbound_video_task.done():
            return
        if session.video_lock is None:
            session.video_lock = asyncio.Lock()

        async def _loop() -> None:
            from ntgcalls import CAMERA, FrameData

            logger.info(
                "telegram call outbound video loop started account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
            )
            next_tick = time.perf_counter()
            while session.media_attached:
                ntgcalls = self._get_ntgcalls()
                if ntgcalls is None:
                    break

                frame = _BLACK_I420
                width, height, rotation, timestamp_ms = (
                    VIDEO_WIDTH,
                    VIDEO_HEIGHT,
                    0,
                    int(time.monotonic() * 1000),
                )
                if session.video_lock is not None:
                    async with session.video_lock:
                        if session.video_frame is not None and session.video_frame_meta is not None:
                            frame = session.video_frame
                            width, height, rotation, timestamp_ms = session.video_frame_meta

                try:
                    ntgcalls.send_external_frame(
                        session.participant_id,
                        CAMERA,
                        frame,
                        FrameData(timestamp_ms, rotation, width, height),
                    )
                    session.video_frames_sent += 1
                    if session.video_frames_sent == 1 or session.video_frames_sent % 75 == 0:
                        logger.info(
                            "telegram call outbound video account=%s call_id=%s frames=%s %sx%s",
                            session.account_id[:8],
                            session.call_id,
                            session.video_frames_sent,
                            width,
                            height,
                        )
                except Exception:
                    logger.debug(
                        "outbound video frame failed account=%s call_id=%s",
                        session.account_id[:8],
                        session.call_id,
                        exc_info=True,
                    )
                    break

                next_tick += VIDEO_FRAME_INTERVAL
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    next_tick = time.perf_counter()
                    await asyncio.sleep(0)

            logger.info(
                "telegram call outbound video loop stopped account=%s call_id=%s frames=%s",
                session.account_id[:8],
                session.call_id,
                session.video_frames_sent,
            )

        try:
            session.outbound_video_task = asyncio.create_task(_loop())
        except RuntimeError:
            session.outbound_video_task = None

    def _stop_outbound_video_loop(self, session: _CallSession) -> None:
        task = session.outbound_video_task
        session.outbound_video_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _ntgcalls_connect_p2p(self, session: _CallSession, phone_call: PhoneCall) -> None:
        ntgcalls = self._get_ntgcalls()
        if ntgcalls is None:
            raise ValidationError("call audio engine is unavailable")

        servers = _build_rtc_servers(phone_call)
        if not servers:
            raise ValidationError("call has no rtc servers")

        versions = _call_library_versions(phone_call)
        custom_parameters = getattr(phone_call, "custom_parameters", None)
        custom_params = getattr(custom_parameters, "data", None) if custom_parameters is not None else None
        if custom_params is not None and not isinstance(custom_params, str):
            custom_params = str(custom_params)

        logger.info(
            "telegram call connect_p2p account=%s call_id=%s servers=%s versions=%s p2p=%s custom=%s",
            session.account_id[:8],
            session.call_id,
            len(servers),
            versions,
            bool(getattr(phone_call, "p2p_allowed", True)),
            bool(custom_params),
        )
        self._prepare_inbound_fifo(session)
        # Always start FIFO reader as fallback if we later switch to FILE,
        # and for when EXTERNAL also mirrors somehow. Harmless if unused.
        self._start_inbound_fifo_reader(session)
        await asyncio.sleep(0.05)
        self._configure_external_streams(session)
        await self._await_ntgcalls(
            ntgcalls.connect_p2p(
                session.participant_id,
                servers,
                versions,
                bool(getattr(phone_call, "p2p_allowed", True)),
                custom_params,
            ),
            timeout=20,
        )
        try:
            ntgcalls.unmute(session.participant_id)
        except Exception:
            logger.debug(
                "ntgcalls unmute failed account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
                exc_info=True,
            )
        try:
            ntgcalls.resume(session.participant_id)
        except Exception:
            logger.debug(
                "ntgcalls resume failed account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
                exc_info=True,
            )

    async def attach_audio_bridge(
        self,
        *,
        account_id: str,
        call_id: int | str,
        operator_user_id: str,
        websocket: Any,
    ) -> None:
        key = self._session_key(account_id, call_id)
        session = self._sessions.get(key)
        if session is None:
            raise ValidationError("call not found")
        if session.operator_user_id and session.operator_user_id != operator_user_id:
            raise ValidationError("call belongs to another operator")

        session.audio_ws = websocket
        await websocket.send_json(
            {
                "type": "ready",
                "status": session.status,
                "sample_rate": AUDIO_SAMPLE_RATE,
                "channels": AUDIO_CHANNELS,
                "frame_samples": AUDIO_FRAME_SAMPLES,
                "video": bool(session.video),
                "width": VIDEO_WIDTH if session.video else 0,
                "height": VIDEO_HEIGHT if session.video else 0,
                "fps": VIDEO_FPS if session.video else 0,
            },
        )
        if session.status == "connected" and session.media_attached:
            await self._notify_call_status(session)
        logger.info(
            "call media bridge attached account=%s call_id=%s status=%s",
            account_id[:8],
            call_id,
            session.status,
        )

    async def detach_audio_bridge(self, account_id: str, call_id: int | str) -> None:
        session = self._sessions.get(self._session_key(account_id, call_id))
        if session is not None:
            session.audio_ws = None
            logger.info(
                "call media bridge detached account=%s call_id=%s",
                account_id[:8],
                call_id,
            )

    async def push_operator_audio(
        self,
        account_id: str,
        call_id: int | str,
        payload: bytes,
    ) -> None:
        session = self._sessions.get(self._session_key(account_id, call_id))
        if session is None or not session.media_attached or not payload:
            return

        if session.audio_lock is None:
            session.audio_lock = asyncio.Lock()

        async with session.audio_lock:
            # Cap buffer ~200ms to avoid latency buildup
            max_bytes = AUDIO_FRAME_BYTES * 20
            session.audio_buffer.extend(payload)
            if len(session.audio_buffer) > max_bytes:
                overflow = len(session.audio_buffer) - max_bytes
                del session.audio_buffer[:overflow]
            session.operator_bytes_queued += len(payload)
            if session.operator_bytes_queued == len(payload) or session.operator_bytes_queued % 96000 < len(payload):
                logger.info(
                    "call media operator audio queued account=%s call_id=%s total_bytes=%s buffer=%s",
                    account_id[:8],
                    call_id,
                    session.operator_bytes_queued,
                    len(session.audio_buffer),
                )

    async def push_operator_video(
        self,
        account_id: str,
        call_id: int | str,
        payload: bytes,
    ) -> None:
        session = self._sessions.get(self._session_key(account_id, call_id))
        if session is None or not session.media_attached or not session.video or not payload:
            return

        parsed = _parse_video_ws_payload(payload)
        if parsed is None:
            return
        width, height, rotation, timestamp_ms, i420 = parsed

        if session.video_lock is None:
            session.video_lock = asyncio.Lock()

        async with session.video_lock:
            # Keep only the latest frame to avoid backlog.
            session.video_frame = i420
            session.video_frame_meta = (width, height, rotation, timestamp_ms)

    async def push_operator_media(
        self,
        account_id: str,
        call_id: int | str,
        payload: bytes,
    ) -> None:
        """Demux framed media WS payloads (type byte + body)."""
        if not payload:
            return
        # Legacy unframed PCM (pre-video protocol).
        if len(payload) == AUDIO_FRAME_BYTES:
            await self.push_operator_audio(account_id, call_id, payload)
            return
        media_type = payload[0]
        body = payload[1:]
        if media_type == MEDIA_TYPE_AUDIO:
            await self.push_operator_audio(account_id, call_id, body)
        elif media_type == MEDIA_TYPE_VIDEO:
            await self.push_operator_video(account_id, call_id, body)

    def _take_live_chunk(self, session: _CallSession, *, force: bool = False) -> bytes | None:
        with session.transcript_lock:
            pending = session.live_pcm
            if len(pending) < 2:
                return None
            if not force and len(pending) < LIVE_MIN_CHUNK_BYTES:
                return None

            should_flush = force or len(pending) >= LIVE_MAX_CHUNK_BYTES
            if not should_flush:
                silence_len = min(LIVE_SILENCE_BYTES, len(pending))
                silence_len -= silence_len % 2
                tail_rms = _pcm_rms_s16le(bytes(pending[-silence_len:])) if silence_len >= 2 else 0.0
                should_flush = tail_rms < LIVE_SILENCE_RMS

            if not should_flush:
                return None

            if force:
                take = len(pending)
            else:
                take = len(pending) - LIVE_OVERLAP_BYTES
            take -= take % 2
            if take < LIVE_MIN_CHUNK_BYTES and not force:
                return None
            if take <= 0:
                return None
            chunk = bytes(pending[:take])
            del pending[:take]
            return chunk

    async def _emit_transcript_event(
        self,
        session: _CallSession,
        text: str,
        *,
        final: bool,
    ) -> None:
        ws = session.audio_ws
        if ws is None or not text.strip():
            return
        payload = {
            "type": "transcript",
            "text": text.strip(),
            "final": final,
        }

        async def _send() -> None:
            try:
                await ws.send_json(payload)
            except Exception:
                logger.debug(
                    "failed to push transcript event account=%s call_id=%s",
                    session.account_id[:8],
                    session.call_id,
                    exc_info=True,
                )

        self._dispatch_coro(session, _send())

    async def _transcribe_live_chunk(
        self,
        session: _CallSession,
        chunk: bytes,
        *,
        final: bool,
    ) -> None:
        from allchats_sdk.internal.hooks.speech import SpeechRecognitionError, transcribe_voice_bytes

        settings = session.live_whisper_settings
        if settings is None or not chunk:
            return
        wav = _pcm_s16le_to_wav(chunk, sample_rate=AUDIO_SAMPLE_RATE, channels=1)
        try:
            text = await transcribe_voice_bytes(wav, ".wav", settings)
        except SpeechRecognitionError:
            logger.warning(
                "live transcript chunk failed account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
                exc_info=True,
            )
            return
        except Exception:
            logger.exception(
                "live transcript chunk error account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
            )
            return

        if not text:
            return

        cleaned = text.strip()
        # Prefer emitting on sentence-like boundaries; still emit on force/max window.
        if not final and not _looks_like_sentence(cleaned):
            # Keep as soft partial: emit anyway so UI stays live, mark final=False.
            await self._emit_transcript_event(session, cleaned, final=False)
            session.live_partial = cleaned
            return

        session.live_partial = ""
        await self._emit_transcript_event(session, cleaned, final=True)
        logger.info(
            "live transcript chunk account=%s call_id=%s final=%s chars=%s",
            session.account_id[:8],
            session.call_id,
            final,
            len(cleaned),
        )

    def _start_live_transcript_loop(self, session: _CallSession) -> None:
        if session.live_task is not None and not session.live_task.done():
            return

        async def _loop() -> None:
            logger.info(
                "live transcript started account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
            )
            try:
                while session.live_transcript_enabled and session.media_attached:
                    if session.live_busy:
                        await asyncio.sleep(LIVE_POLL_INTERVAL)
                        continue
                    chunk = self._take_live_chunk(session, force=False)
                    if chunk:
                        session.live_busy = True
                        try:
                            await self._transcribe_live_chunk(session, chunk, final=True)
                        finally:
                            session.live_busy = False
                    await asyncio.sleep(LIVE_POLL_INTERVAL)
            finally:
                # Flush remainder when stopping.
                leftover = self._take_live_chunk(session, force=True)
                if leftover and session.live_whisper_settings is not None:
                    session.live_busy = True
                    try:
                        await self._transcribe_live_chunk(session, leftover, final=True)
                    finally:
                        session.live_busy = False
                logger.info(
                    "live transcript stopped account=%s call_id=%s",
                    session.account_id[:8],
                    session.call_id,
                )

        try:
            session.live_task = asyncio.create_task(_loop())
        except RuntimeError:
            session.live_task = None

    def _stop_live_transcript_loop(self, session: _CallSession) -> None:
        session.live_transcript_enabled = False
        task = session.live_task
        session.live_task = None
        # Let the loop flush leftover; don't cancel immediately if running.
        if task is not None and not task.done():
            # Soft-stop: loop exits on live_transcript_enabled=False and flushes.
            pass

    async def set_live_transcript(
        self,
        account_id: str,
        call_id: int | str,
        *,
        enabled: bool,
        whisper_settings: Any,
    ) -> dict[str, Any]:
        session = self._sessions.get(self._session_key(account_id, call_id))
        if session is None:
            raise ValidationError("call not found")
        if enabled and not getattr(whisper_settings, "enabled", False):
            raise ValidationError("speech recognition is disabled")

        if enabled:
            if session.live_transcript_enabled:
                return {"call_id": str(call_id), "enabled": True}
            with session.transcript_lock:
                session.live_pcm.clear()
            session.live_partial = ""
            session.live_whisper_settings = whisper_settings
            session.live_transcript_enabled = True
            self._start_live_transcript_loop(session)
            await self._notify_live_transcript_status(session, enabled=True)
            return {"call_id": str(call_id), "enabled": True}

        was_enabled = session.live_transcript_enabled
        session.live_transcript_enabled = False
        task = session.live_task
        session.live_task = None
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(task, timeout=45)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
            except Exception:
                logger.debug(
                    "live transcript stop wait failed account=%s call_id=%s",
                    account_id[:8],
                    call_id,
                    exc_info=True,
                )
        if was_enabled:
            await self._notify_live_transcript_status(session, enabled=False)
        return {"call_id": str(call_id), "enabled": False}

    async def _notify_live_transcript_status(self, session: _CallSession, *, enabled: bool) -> None:
        ws = session.audio_ws
        if ws is None:
            return
        try:
            await ws.send_json({"type": "transcript_status", "enabled": enabled})
        except Exception:
            logger.debug(
                "failed to notify transcript status account=%s call_id=%s",
                session.account_id[:8],
                session.call_id,
                exc_info=True,
            )

    async def end_call(self, client: Any, account_id: str, call_id: int | str) -> None:
        key = self._session_key(account_id, call_id)
        session = self._sessions.get(key)
        if session is None:
            raise ValidationError("call not found")

        duration = max(0, int(time.time() - (session.connected_at or session.started_at)))
        self._schedule_call_log(
            self._persist_call_event(
                session,
                status="ended" if session.connected_at else "rejected",
                duration_sec=duration if session.connected_at else 0,
            )
        )
        try:
            await client(
                DiscardCallRequest(
                    peer=session.peer,
                    duration=duration,
                    reason=PhoneCallDiscardReasonHangup(),
                    connection_id=0,
                    video=session.video,
                ),
            )
        except Exception:
            logger.exception(
                "failed to discard telegram call account=%s call_id=%s",
                account_id[:8],
                call_id,
            )
        finally:
            await self._cleanup_session(session)

    async def _handle_phone_call_update(
        self,
        client: Any,
        account_id: str,
        phone_call: Any,
    ) -> None:
        if isinstance(phone_call, PhoneCallRequested):
            await self._record_incoming_request(client, account_id, phone_call)
            return

        if isinstance(phone_call, PhoneCallAccepted):
            await self._confirm_outgoing_call(client, account_id, phone_call)
            return

        if isinstance(phone_call, PhoneCall):
            session = self._sessions.get(self._session_key(account_id, int(phone_call.id)))
            if session is not None:
                session.status = "connected"
                session.connected_at = time.time()
                self._schedule_call_log(self._persist_call_event(session, status="answered"))
            logger.info(
                "telegram call connected account=%s call_id=%s",
                account_id[:8],
                phone_call.id,
            )
            await self._attach_media(account_id, phone_call)
            if session is not None:
                await self._notify_call_status(session)
            return

        if isinstance(phone_call, PhoneCallDiscarded):
            session = self._sessions.pop(self._session_key(account_id, int(phone_call.id)), None)
            if session is not None:
                reason_name = type(getattr(phone_call, "reason", None)).__name__
                if session.connected_at:
                    status = "ended"
                elif "Missed" in reason_name:
                    status = "missed"
                elif "Busy" in reason_name:
                    status = "busy"
                else:
                    status = "rejected" if session.direction == "incoming" else "missed"
                duration = getattr(phone_call, "duration", None)
                session.status = "ended"
                self._schedule_call_log(
                    self._persist_call_event(
                        session,
                        status=status,
                        duration_sec=int(duration) if duration is not None else None,
                    )
                )
                await self._notify_call_status(session)
                await self._cleanup_session(session, discard_remote=False)
            logger.info(
                "telegram call discarded account=%s call_id=%s reason=%s",
                account_id[:8],
                phone_call.id,
                type(getattr(phone_call, "reason", None)).__name__,
            )

    async def _record_incoming_request(
        self,
        client: Any,
        account_id: str,
        phone_call: PhoneCallRequested,
    ) -> None:
        from telethon import utils
        from telethon.tl.types import User

        participant_id = int(getattr(phone_call, "participant_id", 0) or 0)
        admin_id = int(getattr(getattr(phone_call, "admin_id", None), "user_id", 0) or getattr(phone_call, "admin_id", 0) or 0)
        # For incoming, admin is the caller.
        peer_user_id = admin_id or participant_id
        peer_title = str(peer_user_id)
        peer_external_id = str(peer_user_id)
        try:
            entity = await client.get_entity(peer_user_id)
            if isinstance(entity, User):
                peer_external_id = str(utils.get_peer_id(entity))
                first = str(getattr(entity, "first_name", "") or "").strip()
                last = str(getattr(entity, "last_name", "") or "").strip()
                peer_title = " ".join(part for part in (first, last) if part).strip() or peer_external_id
        except Exception:
            logger.debug("failed to resolve incoming call peer", exc_info=True)

        call_id = int(phone_call.id)
        session = _CallSession(
            account_id=account_id,
            call_id=call_id,
            peer=InputPhoneCall(call_id, phone_call.access_hash),
            g_a_hash=b"",
            video=bool(getattr(phone_call, "video", False)),
            participant_id=peer_user_id or participant_id,
            operator_user_id="",
            client=client,
            direction="incoming",
            peer_external_id=peer_external_id,
            peer_title=peer_title,
            status="ringing",
            loop=asyncio.get_running_loop(),
        )
        # Do not keep unanswered incoming in active media sessions — only log.
        self._schedule_call_log(self._persist_call_event(session, status="ringing"))
        logger.info(
            "telegram incoming call account=%s call_id=%s peer=%s video=%s",
            account_id[:8],
            call_id,
            peer_external_id,
            session.video,
        )

    async def _confirm_outgoing_call(
        self,
        client: Any,
        account_id: str,
        phone_call: PhoneCallAccepted,
    ) -> None:
        session = self._sessions.get(self._session_key(account_id, int(phone_call.id)))
        if session is None:
            return

        auth = await self._ntgcalls_exchange_keys(session, phone_call.g_b)
        if auth is None:
            logger.error(
                "telegram call key exchange failed account=%s call_id=%s",
                account_id[:8],
                phone_call.id,
            )
            return

        result = await client(
            ConfirmCallRequest(
                peer=InputPhoneCall(phone_call.id, phone_call.access_hash),
                g_a=bytes(auth.g_a_or_b),
                key_fingerprint=int(auth.key_fingerprint),
                protocol=get_call_protocol(),
            ),
        )
        logger.info(
            "telegram call confirmed account=%s call_id=%s",
            account_id[:8],
            phone_call.id,
        )
        confirmed_call = getattr(result, "phone_call", None)
        if isinstance(confirmed_call, PhoneCall):
            session.status = "connected"
            session.connected_at = time.time()
            await self._attach_media(account_id, confirmed_call)
            await self._notify_call_status(session)

    async def _attach_media(self, account_id: str, phone_call: PhoneCall) -> None:
        session = self._sessions.get(self._session_key(account_id, int(phone_call.id)))
        if session is None or session.media_attached or session.media_connecting:
            return

        session.media_connecting = True
        try:
            await self._ntgcalls_connect_p2p(session, phone_call)
        except Exception:
            logger.exception(
                "telegram call media connect failed account=%s call_id=%s",
                account_id[:8],
                phone_call.id,
            )
            return
        finally:
            session.media_connecting = False

        session.media_attached = True
        self._start_outbound_audio_loop(session)
        self._start_outbound_video_loop(session)
        logger.info(
            "telegram call media attached account=%s call_id=%s participant=%s servers=%s video=%s",
            account_id[:8],
            phone_call.id,
            session.participant_id,
            len(_build_rtc_servers(phone_call)),
            session.video,
        )

    async def _handle_signaling_data(
        self,
        account_id: str,
        call_id: int,
        data: bytes,
    ) -> None:
        session = self._sessions.get(self._session_key(account_id, call_id))
        if session is None:
            return

        ntgcalls = self._get_ntgcalls()
        if ntgcalls is None:
            return

        try:
            ntgcalls.send_signaling(session.participant_id, data)
            logger.debug(
                "telegram call signaling in account=%s call_id=%s bytes=%s",
                account_id[:8],
                call_id,
                len(data),
            )
        except Exception:
            logger.exception(
                "failed to deliver telegram call signaling account=%s call_id=%s",
                account_id[:8],
                call_id,
            )

    async def _cleanup_session(self, session: _CallSession, *, discard_remote: bool = True) -> None:
        session.live_transcript_enabled = False
        live_task = session.live_task
        session.live_task = None
        if live_task is not None and not live_task.done():
            try:
                await asyncio.wait_for(live_task, timeout=8)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                live_task.cancel()
            except Exception:
                pass
        self._stop_outbound_audio_loop(session)
        self._stop_outbound_video_loop(session)
        self._stop_inbound_fifo_reader(session)
        ntgcalls = self._get_ntgcalls()
        if ntgcalls is not None:
            try:
                ntgcalls.stop(session.participant_id)
            except Exception:
                logger.debug(
                    "ntgcalls.stop failed account=%s call_id=%s",
                    session.account_id[:8],
                    session.call_id,
                    exc_info=True,
                )

        ws = session.audio_ws
        session.audio_ws = None
        if ws is not None:
            try:
                await ws.send_json({"type": "status", "status": "ended"})
                await ws.close()
            except Exception:
                pass

        if session.connected_at and session.record_call:
            remote_pcm = bytes(session.recording_remote)
            local_pcm = bytes(session.recording_local)
            recording_service = self._call_recording_service
            if recording_service is not None and (remote_pcm or local_pcm):
                recording_service.schedule_telegram_finalize(
                    account_id=session.account_id,
                    external_call_id=str(session.call_id),
                    remote_pcm=remote_pcm,
                    local_pcm=local_pcm,
                    sample_rate=AUDIO_SAMPLE_RATE,
                )

        self._sessions.pop(self._session_key(session.account_id, session.call_id), None)


telegram_call_coordinator = TelegramCallCoordinator()
