from __future__ import annotations

from typing import TYPE_CHECKING

from pymax.auth.models import AuthResult
from pymax.auth.sms import SmsAuthFlow

if TYPE_CHECKING:
    from allchats_sdk.protocols import SessionManager, SessionRuntime


class WebSmsAuthFlow(SmsAuthFlow):
    def __init__(
        self,
        runtime: SessionRuntime,
        manager: SessionManager,
        *,
        code_provider,
        password_provider=None,
    ) -> None:
        super().__init__(code_provider, password_provider=password_provider)
        self._runtime = runtime
        self._manager = manager

    async def authenticate(self, app) -> AuthResult:
        phone = app.config.phone
        if not phone:
            raise RuntimeError("Phone is required for SMS authentication")

        start = await app.api.auth.request_code(phone)
        await self._manager.set_sms_token(self._runtime.snapshot.session_id, start.token)

        code = await self.code_provider.get_code(phone)
        result = await app.api.auth.send_code(start.token, code)

        if result.login_token:
            token = result.login_token
        elif result.password_challenge:
            await self._manager.set_password_challenge(
                self._runtime.snapshot.session_id,
                track_id=result.password_challenge.track_id,
                hint=result.password_challenge.hint,
            )
            token = await self._authenticate_with_password(
                app,
                track_id=result.password_challenge.track_id,
                hint=result.password_challenge.hint,
            )
        elif result.register_token:
            if not app.config.registration_config:
                raise RuntimeError("RegistrationConfig is required to register a new account")
            registration_config = app.config.registration_config
            response = await app.api.auth.confirm_registration(
                first_name=registration_config.first_name,
                last_name=registration_config.last_name,
                token=result.register_token,
            )
            token = response.token
        else:
            raise RuntimeError(
                "Authentication failed: server returned no login token, "
                "password challenge, or registration token"
            )

        return AuthResult(token=token)
