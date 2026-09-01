from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from pymax.auth.models import AuthResult
from pymax.auth.qr import QrAuthFlow

from allchats_sdk.providers.max.providers import WebQrHandler

if TYPE_CHECKING:
    from allchats_sdk.host.ports import SessionManager, SessionRuntime


class WebQrAuthFlow(QrAuthFlow):
    def __init__(
        self,
        runtime: SessionRuntime,
        manager: SessionManager,
        *,
        password_provider,
    ) -> None:
        super().__init__(WebQrHandler(runtime, manager), password_provider=password_provider)
        self._runtime = runtime
        self._manager = manager

    async def authenticate(self, app) -> AuthResult:
        qr_info = await app.api.auth.request_qr()
        await self._manager.set_qr_info(
            self._runtime.snapshot.session_id,
            qr_link=qr_info.qr_link,
            track_id=qr_info.track_id,
            polling_interval=qr_info.polling_interval,
            expires_at=qr_info.expires_at,
        )

        try:
            confirmed = await self._poll_qr(app, qr_info)
            if not confirmed:
                raise RuntimeError("QR authentication expired")

            result = await app.api.auth.confirm_qr(qr_info.track_id)
            token = result.login_token
            if not token and result.password_challenge:
                token = await self._authenticate_with_password(
                    app,
                    track_id=result.password_challenge.track_id,
                    hint=result.password_challenge.hint,
                )
        except Exception as exc:
            await self._manager.update_qr_watcher(
                self._runtime.snapshot.session_id,
                login_available=False,
                expires_at=0,
                error=str(exc),
            )
            raise

        return AuthResult(token=token)

    async def _poll_qr(self, app, qr_info) -> bool:
        interval = qr_info.polling_interval / 1000
        expires_at_sec = qr_info.expires_at / 1000
        session_id = self._runtime.snapshot.session_id

        await self._manager.update_qr_watcher(
            session_id,
            login_available=True,
            expires_at=qr_info.expires_at,
            error=None,
        )

        while time.time() < expires_at_sec:
            try:
                response = await app.api.auth.check_qr(qr_info.track_id)
            except Exception as exc:
                await self._manager.update_qr_watcher(
                    session_id,
                    login_available=False,
                    expires_at=0,
                    error=str(exc),
                )
                return False

            if response.status.login_available:
                return True

            await self._manager.update_qr_watcher(
                session_id,
                login_available=True,
                expires_at=qr_info.expires_at,
            )
            await asyncio.sleep(interval)

        await self._manager.update_qr_watcher(
            session_id,
            login_available=False,
            expires_at=qr_info.expires_at,
            error="QR session not active, request a new QR",
        )
        return False
