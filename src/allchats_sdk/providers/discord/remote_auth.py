from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

logger = logging.getLogger(__name__)

DEFAULT_ORIGIN = "https://discord.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) discord/0.0.330 Chrome/128.0.6613.186 "
    "Electron/32.2.0 Safari/537.36"
)


@dataclass
class RemoteAuthResult:
    token: str
    fingerprint: str = ""


class DiscordRemoteAuthError(Exception):
    pass


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


class DiscordRemoteAuthSession:
    def __init__(self) -> None:
        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._public_der = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.encoded_public_key = base64.b64encode(self._public_der).decode("ascii")
        self.expected_fingerprint = _b64url(hashlib.sha256(self._public_der).digest())
        self.fingerprint = ""
        self.qr_link = ""

    def decrypt(self, encrypted_b64: str) -> bytes:
        encrypted = base64.b64decode(encrypted_b64)
        return self._private_key.decrypt(
            encrypted,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

    def nonce_proof(self, encrypted_nonce: str) -> str:
        # Discord remote-auth v2 expects the decrypted nonce itself, URL-safe base64.
        nonce = self.decrypt(encrypted_nonce)
        return _b64url(nonce)

    def decrypt_token(self, encrypted_token: str) -> str:
        return self.decrypt(encrypted_token).decode("utf-8")


@asynccontextmanager
async def _open_ws(
    ws_url: str,
    *,
    origin: str,
    user_agent: str,
    proxy_url: str | None,
) -> AsyncIterator[Any]:
    import websockets

    headers = {
        "Origin": origin,
        "User-Agent": user_agent,
    }
    connect_kwargs: dict[str, Any] = {
        "max_size": 8 * 1024 * 1024,
        "open_timeout": 20,
        "ping_interval": None,
        "additional_headers": headers,
    }

    if not proxy_url:
        async with websockets.connect(ws_url, **connect_kwargs) as ws:
            yield ws
        return

    try:
        # v1 API returns a real socket.socket (websockets needs .family/.type).
        # v2's AsyncioSocketStream is incompatible with websockets.connect(sock=...).
        from python_socks.async_.asyncio import Proxy
    except ImportError as exc:
        raise DiscordRemoteAuthError(
            "proxy support requires python-socks; install python-socks[asyncio]"
        ) from exc

    parsed = urlparse(ws_url)
    host = parsed.hostname or "remote-auth-gateway.discord.gg"
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    proxy = Proxy.from_url(proxy_url)
    sock = await proxy.connect(dest_host=host, dest_port=port)
    async with websockets.connect(
        ws_url,
        sock=sock,
        server_hostname=host,
        ssl=parsed.scheme == "wss",
        **connect_kwargs,
    ) as ws:
        yield ws


async def run_remote_auth(
    *,
    ws_url: str,
    exchange_ticket: Callable[[str], Awaitable[dict[str, Any]]],
    on_qr: Callable[[str, str], Awaitable[None]] | None = None,
    on_opened: Callable[[], Awaitable[None]] | None = None,
    should_stop: Callable[[], bool] | None = None,
    proxy_url: str | None = None,
    origin: str = DEFAULT_ORIGIN,
    user_agent: str = DEFAULT_USER_AGENT,
) -> RemoteAuthResult:
    """Run Discord remote-auth v2 until a user token is obtained."""
    session = DiscordRemoteAuthSession()
    heartbeat_task: asyncio.Task[None] | None = None

    try:
        async with _open_ws(
            ws_url,
            origin=origin,
            user_agent=user_agent,
            proxy_url=proxy_url,
        ) as ws:
            while True:
                if should_stop and should_stop():
                    raise DiscordRemoteAuthError("cancelled")

                raw = await ws.recv()
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                message = json.loads(raw)
                op = str(message.get("op") or "")

                if op == "hello":
                    interval_ms = int(message.get("heartbeat_interval") or 41250)
                    await ws.send(
                        json.dumps(
                            {
                                "op": "init",
                                "encoded_public_key": session.encoded_public_key,
                            }
                        )
                    )

                    async def _heartbeat_loop() -> None:
                        while True:
                            await asyncio.sleep(max(interval_ms / 1000.0, 5.0))
                            try:
                                await ws.send(json.dumps({"op": "heartbeat"}))
                            except Exception:
                                return

                    if heartbeat_task is not None:
                        heartbeat_task.cancel()
                    heartbeat_task = asyncio.create_task(_heartbeat_loop())
                    continue

                if op == "nonce_proof":
                    encrypted_nonce = str(message.get("encrypted_nonce") or "")
                    if not encrypted_nonce:
                        raise DiscordRemoteAuthError("missing encrypted_nonce")
                    proof = session.nonce_proof(encrypted_nonce)
                    await ws.send(json.dumps({"op": "nonce_proof", "nonce": proof}))
                    continue

                if op == "pending_remote_init":
                    fingerprint = str(message.get("fingerprint") or "").strip()
                    if not fingerprint:
                        raise DiscordRemoteAuthError("missing fingerprint")
                    if fingerprint != session.expected_fingerprint:
                        raise DiscordRemoteAuthError("fingerprint mismatch")
                    session.fingerprint = fingerprint
                    session.qr_link = f"https://discord.com/ra/{fingerprint}"
                    if on_qr is not None:
                        await on_qr(session.qr_link, fingerprint)
                    continue

                if op == "pending_ticket":
                    if on_opened is not None:
                        await on_opened()
                    continue

                if op == "pending_login":
                    ticket = str(message.get("ticket") or "").strip()
                    if not ticket:
                        raise DiscordRemoteAuthError("missing remote-auth ticket")
                    try:
                        payload = await exchange_ticket(ticket)
                        encrypted_token = str(payload.get("encrypted_token") or "").strip()
                        if not encrypted_token:
                            raise DiscordRemoteAuthError("missing encrypted_token")
                        token = session.decrypt_token(encrypted_token).strip()
                    except Exception as exchange_exc:
                        # Some Discord builds deliver the encrypted token in `ticket`
                        # itself; if REST exchange is rejected, try decrypting it.
                        try:
                            token = session.decrypt_token(ticket).strip()
                            logger.info(
                                "discord remote-auth used direct ticket decrypt after exchange failure: %s",
                                exchange_exc,
                            )
                        except Exception:
                            raise DiscordRemoteAuthError(str(exchange_exc) or "ticket exchange failed") from exchange_exc
                    if not token:
                        raise DiscordRemoteAuthError("empty discord token")
                    return RemoteAuthResult(token=token, fingerprint=session.fingerprint)

                if op == "cancel":
                    raise DiscordRemoteAuthError("qr cancelled on client")

                if op == "heartbeat_ack":
                    continue

                logger.debug("discord remote-auth ignored op=%s", op)
    except DiscordRemoteAuthError:
        raise
    except Exception as exc:
        raise DiscordRemoteAuthError(str(exc) or "remote-auth failed") from exc
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
