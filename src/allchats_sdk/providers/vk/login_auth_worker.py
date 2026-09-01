from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import vk_api
from vk_api.credentials import WebLoginCredentials
from vk_api.enums import VerificationMethod
from vk_api.exceptions import AuthError, Captcha, SecurityCheck
from vk_api.utils import clear_string, code_from_number, search_re

from allchats_sdk.providers.vk.client import API_VERSION
from allchats_sdk.providers.vk.manager import VkClientManager
from allchats_sdk.observability import record_auth

logger = logging.getLogger(__name__)

RE_NUMBER_HASH = re.compile(r"al_page: '3', hash: '([a-z0-9]+)'")
RE_PHONE_PREFIX = re.compile(r'label ta_r">\+(.*?)<')
RE_PHONE_POSTFIX = re.compile(r'phone_postfix">.*?(\d+).*?<')
RE_LOGIN_LG_DOMAIN_H = re.compile(r'name="lg_domain_h" value="([a-z0-9]+)"')


class BridgeVkApi(vk_api.VkApi):
    def __init__(
        self,
        *,
        manager: VkClientManager,
        account_id: str,
        loop: asyncio.AbstractEventLoop,
        sms_mode: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._bridge_manager = manager
        self._bridge_account_id = account_id
        self._bridge_loop = loop
        self._sms_mode = sms_mode

    def _wait_verification_code(self, *, kind: str, hint: str = "") -> tuple[str, bool]:
        future = asyncio.run_coroutine_threadsafe(
            self._bridge_manager.wait_verification_code(
                self._bridge_account_id,
                kind=kind,
                hint=hint,
            ),
            self._bridge_loop,
        )
        return future.result(timeout=300)

    def auth_handler(self) -> tuple[str, bool]:
        kind = "sms" if self._sms_mode else "twofactor"
        return self._wait_verification_code(kind=kind)

    def _auth_token(self, reauth: bool = False) -> None:
        if not reauth and self._check_token():
            self.logger.info("access_token from config is valid")
            return

        if reauth:
            self.logger.info("Auth (API) forced")

        if self.check_sid():
            self._pass_security_check()
            self._api_login()
        elif self.password or self._sms_mode:
            self._vk_login()
            self._api_login()

    def _vk_login(self, captcha_sid: str | None = None, captcha_key: str | None = None) -> None:
        if not self._sms_mode:
            return super()._vk_login(captcha_sid, captcha_key)

        self.logger.info("Logging in via SMS...")

        self.http.cookies.clear()
        response = self.http.get("https://vk.ru/")

        if response.url.startswith("https://vk.ru/429.html?"):
            hash429_md5 = __import__("hashlib").md5(
                self.http.cookies["hash429"].encode("ascii")
            ).hexdigest()
            self.http.cookies.pop("hash429")
            response = self.http.get(f"{response.url}&key={hash429_md5}")

        response = self._check_challenge(response)

        if search_re(RE_LOGIN_LG_DOMAIN_H, response.text):
            raise AuthError("Legacy VK login form does not support SMS-only auth")

        credentials = WebLoginCredentials(self.http)
        time.sleep(0.5)

        account = self.method(
            with_cookies=True,
            method="auth.validateAccount",
            values={
                "v": credentials.api_version,
                "client_id": credentials.app_id,
                "login": self.login,
                "sid": credentials.sid,
                "device_id": credentials.device_id,
                "auth_token": credentials.access_token,
                "super_app_token": "",
                "supported_ways": ",".join(VerificationMethod),
                "is_switcher_flow": "0",
                "is_edu_flow": "",
                "is_registration": "",
                "access_token": "",
            },
        )

        if "sid" not in account:
            raise AuthError("Account not exists")

        credentials.sid = account["sid"]
        allowed_methods = self._get_allowed_verification_methods(credentials)
        if VerificationMethod.SMS not in allowed_methods:
            raise AuthError("SMS verification is not available for this account")

        self._pass_confirmation_code(VerificationMethod.SMS, credentials)

        if not credentials.can_skip_password and not self.password:
            raise AuthError("SMS verification did not unlock passwordless login")

        response_dict = self.vk_login_method(
            action="connect_authorize",
            values={
                "username": self.login,
                "password": self.password,
                "auth_token": credentials.access_token,
                "sid": credentials.sid,
                "uuid": credentials.uuid,
                "device_id": credentials.device_id,
                "app_id": credentials.app_id,
                "v": credentials.api_version,
                "service_group": "",
                "save_user": "1",
                "version": "1",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "origin": "https://id.vk.ru",
                "referer": "https://id.vk.ru/",
            },
        )

        if response_dict["is_user_banned"]:
            raise AuthError("Account is blocked")

        if not self._sid:
            raise AuthError("Auth failed: no session cookie")

        self.logger.info("Got remixsid")
        from vk_api.utils import cookies_to_list

        self.storage.cookies = cookies_to_list(self.http.cookies)
        self.storage.save()
        self._pass_security_check(response)

    def _pass_security_check(self, response=None):
        self.logger.info("Checking security check request")

        if response is None:
            response = self.http.get("https://vk.ru/settings")

        if "security_check" not in response.url:
            self.logger.info("Security check is not required")
            return response

        phone_prefix = clear_string(search_re(RE_PHONE_PREFIX, response.text))
        phone_postfix = clear_string(search_re(RE_PHONE_POSTFIX, response.text))

        code = None
        if self.login and phone_prefix and phone_postfix:
            code = code_from_number(phone_prefix, phone_postfix, self.login)

        if not code and phone_prefix and phone_postfix:
            hint = f"+{phone_prefix} ... {phone_postfix}"
            code, _ = self._wait_verification_code(kind="security", hint=hint)

        if code:
            number_hash = search_re(RE_NUMBER_HASH, response.text)
            values = {
                "act": "security_check",
                "al": "1",
                "al_page": "3",
                "code": code,
                "hash": number_hash,
                "to": "",
            }
            response = self.http.post("https://vk.ru/login.php", values)
            if response.text.split("<!>")[4] == "4":
                return response

        if phone_prefix and phone_postfix:
            raise SecurityCheck(phone_prefix, phone_postfix)

        raise SecurityCheck(response=response)


async def run_vk_login_auth_worker(
    account_id: str,
    *,
    login: str,
    password: str,
    app_id: int,
    manager: VkClientManager,
    sms_mode: bool = False,
    proxies: dict[str, str] | None = None,
) -> None:
    loop = asyncio.get_running_loop()

    def captcha_handler(captcha: Captcha) -> object:
        future = asyncio.run_coroutine_threadsafe(
            manager.wait_captcha_key(account_id, captcha),
            loop,
        )
        key = future.result(timeout=300)
        return captcha.try_code(key)

    def _do_auth() -> str:
        session = BridgeVkApi(
            manager=manager,
            account_id=account_id,
            loop=loop,
            sms_mode=sms_mode,
            login=login,
            password=password,
            app_id=app_id,
            api_version=API_VERSION,
            captcha_handler=captcha_handler,
        )
        if proxies:
            session.http.proxies.update(proxies)
        session.auth(token_only=True)
        token = str(session.token.get("access_token") or "").strip()
        if not token:
            raise AuthError("access_token missing after vk login auth")
        return token

    auth_method = "sms" if sms_mode else "login"
    try:
        access_token = await asyncio.to_thread(_do_auth)
        await manager.connect_with_token(
            account_id,
            access_token=access_token,
            auth_method=auth_method,
        )
    except Exception as exc:
        logger.warning("vk login auth failed account=%s: %s", account_id[:8], exc)
        manager.set_client_state(
            account_id,
            state_instance="notAuthorized",
            error=str(exc),
            running=False,
        )
        record_auth("vk", "failed")
        raise
    finally:
        manager.cleanup_login_auth(account_id)
