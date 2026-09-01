from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket
from fastapi.websockets import WebSocketState

from allchats_sdk.providers.discord.voice_udp import (
    MONO_FRAME_BYTES,
    mix_mono_frames,
)

if TYPE_CHECKING:
    from allchats_sdk.providers.discord.manager import DiscordClientManager

logger = logging.getLogger(__name__)

MEDIA_TYPE_AUDIO = 0


class DiscordVoiceAudioBridge:
    """Operator PCM WebSocket bridge for a Discord voice session."""

    def __init__(self, account_id: str, manager: DiscordClientManager) -> None:
        self.account_id = account_id
        self.manager = manager
        self.websocket: WebSocket | None = None
        # Anything with push_pcm(bytes) — VoiceClient session or legacy UDP transport.
        self.transport: Any | None = None
        self._operator_user_id: str = ""
        self._inbound_by_ssrc: dict[int, bytes] = {}
        self._inbound_lock = asyncio.Lock()
        self._pending_pcm = bytearray()
        self._pump_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def attach(
        self,
        *,
        websocket: WebSocket,
        operator_user_id: str,
    ) -> None:
        if self.websocket is not None:
            try:
                await self.websocket.close(code=4000)
            except Exception:
                pass
        self.websocket = websocket
        self._operator_user_id = operator_user_id
        await websocket.send_json(
            {
                "type": "ready",
                "account_id": self.account_id,
                "channel_id": (self.manager.voice_session(self.account_id) or {}).get("channel_id"),
            }
        )
        if self._pump_task is None or self._pump_task.done():
            self._stop.clear()
            self._pump_task = asyncio.create_task(
                self._pump_remote_audio(),
                name=f"discord-voice-pump-{self.account_id[:8]}",
            )
        logger.info(
            "discord voice media attached account=%s user=%s",
            self.account_id[:8],
            operator_user_id[:8],
        )

    def bind_transport(self, transport: Any) -> None:
        self.transport = transport
        if self._pending_pcm and transport is not None:
            transport.push_pcm(bytes(self._pending_pcm))
            self._pending_pcm.clear()

    async def push_operator_media(self, payload: bytes) -> None:
        if not payload:
            return
        pcm = payload[1:] if payload[0] == MEDIA_TYPE_AUDIO else payload
        if self.transport is not None:
            self.transport.push_pcm(pcm)
            return
        self._pending_pcm.extend(pcm)
        # Cap backlog ~1s to avoid unbounded growth before UDP is ready.
        max_bytes = MONO_FRAME_BYTES * 100
        if len(self._pending_pcm) > max_bytes:
            del self._pending_pcm[:-max_bytes]

    async def on_remote_pcm(self, ssrc: int, mono_pcm: bytes) -> None:
        async with self._inbound_lock:
            self._inbound_by_ssrc[int(ssrc)] = mono_pcm

    async def detach(self) -> None:
        self._stop.set()
        if self._pump_task is not None and not self._pump_task.done():
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
        self._pump_task = None
        ws = self.websocket
        self.websocket = None
        if ws is not None and ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.close()
            except Exception:
                pass

    async def _pump_remote_audio(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            async with self._inbound_lock:
                frames = list(self._inbound_by_ssrc.values())
                self._inbound_by_ssrc.clear()
            if frames and self.websocket is not None:
                mixed = mix_mono_frames(frames)
                packet = bytes([MEDIA_TYPE_AUDIO]) + mixed
                try:
                    if self.websocket.client_state == WebSocketState.CONNECTED:
                        await self.websocket.send_bytes(packet)
                except Exception:
                    break
            elapsed = time.monotonic() - started
            delay = max(0.0, 0.02 - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                continue


_bridges: dict[str, DiscordVoiceAudioBridge] = {}


def get_or_create_bridge(account_id: str, manager: DiscordClientManager) -> DiscordVoiceAudioBridge:
    bridge = _bridges.get(account_id)
    if bridge is None:
        bridge = DiscordVoiceAudioBridge(account_id, manager)
        _bridges[account_id] = bridge
    return bridge


async def detach_bridge(account_id: str) -> None:
    bridge = _bridges.pop(account_id, None)
    if bridge is not None:
        await bridge.detach()
