from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from typing import Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.6613.186 Safari/537.36"
)


class DiscordApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _super_properties(user_agent: str) -> str:
    props = {
        "os": "Mac OS X",
        "browser": "Chrome",
        "device": "",
        "system_locale": "en-US",
        "has_client_mods": False,
        "browser_user_agent": user_agent,
        "browser_version": "128.0.6613.186",
        "os_version": "10.15.7",
        "referrer": "https://discord.com/login",
        "referring_domain": "discord.com",
        "referrer_current": "",
        "referring_domain_current": "",
        "release_channel": "stable",
        "client_build_number": 365000,
        "client_event_source": None,
        "client_launch_id": str(uuid.uuid4()),
        "client_app_state": "focused",
    }
    raw = json.dumps(props, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _headers(
    *,
    token: str | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    referer: str = "https://discord.com/channels/@me",
    fingerprint: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://discord.com",
        "Referer": referer,
        "X-Discord-Locale": "en-US",
        "X-Discord-Timezone": "UTC",
        "X-Super-Properties": _super_properties(user_agent),
        "X-Debug-Options": "bugReporterEnabled",
    }
    if fingerprint:
        headers["X-Fingerprint"] = fingerprint
    if token:
        headers["Authorization"] = token
    if extra:
        headers.update(extra)
    return headers


def is_captcha_challenge(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("captcha_sitekey"):
        return True
    captcha_key = payload.get("captcha_key")
    return bool(captcha_key)


def extract_captcha_challenge(payload: dict[str, Any]) -> dict[str, str]:
    sitekey = str(payload.get("captcha_sitekey") or "").strip()
    service = str(payload.get("captcha_service") or "hcaptcha").strip() or "hcaptcha"
    session_id = str(payload.get("captcha_session_id") or "").strip()
    rqdata = str(payload.get("captcha_rqdata") or "").strip()
    rqtoken = str(payload.get("captcha_rqtoken") or "").strip()
    return {
        "captcha_sitekey": sitekey,
        "captcha_service": service,
        "captcha_session_id": session_id,
        "captcha_rqdata": rqdata,
        "captcha_rqtoken": rqtoken,
    }


def _error_message(status_code: int, payload: Any) -> str:
    if isinstance(payload, dict):
        if is_captcha_challenge(payload):
            return "discord captcha required"
        message = str(payload.get("message") or payload.get("error") or "").strip()
        if message:
            return message
        code = payload.get("code")
        if code is not None:
            return f"discord http {status_code} (code={code})"
    return f"discord http {status_code}"


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    json_body: dict[str, Any] | None = None,
    proxies: dict[str, str] | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    referer: str = "https://discord.com/channels/@me",
    fingerprint: str | None = None,
    extra_headers: dict[str, str] | None = None,
    accept_captcha: bool = False,
    timeout: float | tuple[float, float] = (10.0, 20.0),
) -> Any:
    try:
        response = requests.request(
            method,
            url,
            headers=_headers(
                token=token,
                user_agent=user_agent,
                referer=referer,
                fingerprint=fingerprint,
                extra=extra_headers,
            ),
            json=json_body,
            proxies=proxies,
            # (connect, read) — dead HTTP CONNECT tunnels previously hung past a single timeout.
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise DiscordApiError(f"discord request failed: {exc}") from exc

    if response.status_code == 204:
        return None

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}

    if response.status_code >= 400:
        if accept_captcha and response.status_code == 400 and is_captcha_challenge(payload):
            return payload
        message = _error_message(response.status_code, payload)
        logger.warning(
            "discord api error status=%s url=%s message=%s payload=%s",
            response.status_code,
            url,
            message,
            payload,
        )
        raise DiscordApiError(
            message,
            status_code=response.status_code,
            payload=payload,
        )
    return payload


def _fetch_fingerprint(
    *,
    api_base: str,
    proxies: dict[str, str] | None,
    user_agent: str,
) -> str | None:
    try:
        payload = _request(
            "GET",
            f"{api_base.rstrip('/')}/experiments",
            proxies=proxies,
            user_agent=user_agent,
            referer="https://discord.com/login",
            timeout=20,
        )
    except DiscordApiError as exc:
        logger.warning("discord experiments fingerprint failed: %s", exc)
        return None
    if not isinstance(payload, dict):
        return None
    fingerprint = str(payload.get("fingerprint") or "").strip()
    return fingerprint or None


async def login(
    *,
    api_base: str,
    login: str,
    password: str,
    proxies: dict[str, str] | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    captcha_key: str | None = None,
    captcha_session_id: str | None = None,
    captcha_rqtoken: str | None = None,
) -> dict[str, Any]:
    captcha_headers: dict[str, str] = {}
    if captcha_key:
        captcha_headers["X-Captcha-Key"] = captcha_key
    if captcha_session_id:
        captcha_headers["X-Captcha-Session-Id"] = captcha_session_id
    if captcha_rqtoken:
        captcha_headers["X-Captcha-Rqtoken"] = captcha_rqtoken

    payload = await asyncio.to_thread(
        _request,
        "POST",
        f"{api_base.rstrip('/')}/auth/login",
        json_body={
            "login": login,
            "password": password,
            "undelete": False,
            "login_source": None,
            "gift_code_sku_id": None,
        },
        proxies=proxies,
        user_agent=user_agent,
        referer="https://discord.com/login",
        extra_headers=captcha_headers or None,
        accept_captcha=True,
    )
    if not isinstance(payload, dict):
        raise DiscordApiError("unexpected login response")
    return payload


async def submit_mfa_totp(
    *,
    api_base: str,
    ticket: str,
    code: str,
    proxies: dict[str, str] | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    payload = await asyncio.to_thread(
        _request,
        "POST",
        f"{api_base.rstrip('/')}/auth/mfa/totp",
        json_body={
            "code": code.strip(),
            "ticket": ticket,
            "login_source": None,
            "gift_code_sku_id": None,
        },
        proxies=proxies,
        user_agent=user_agent,
    )
    if not isinstance(payload, dict):
        raise DiscordApiError("unexpected mfa response")
    return payload


def _proxy_url(proxies: dict[str, str] | None) -> str | None:
    if not proxies:
        return None
    return proxies.get("https") or proxies.get("http")


def _exchange_with_curl_cffi(
    *,
    api_base: str,
    ticket: str,
    proxy_url: str | None,
    user_agent: str,
) -> dict[str, Any]:
    from curl_cffi import requests as curl_requests

    session = curl_requests.Session(impersonate="chrome131")
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}

    headers = _headers(
        user_agent=user_agent,
        referer="https://discord.com/login",
    )
    # Warm cookies / Cloudflare clearance similarly to a browser login page visit.
    try:
        session.get("https://discord.com/login", headers=headers, timeout=20)
    except Exception as exc:
        logger.debug("discord login page warm-up failed: %s", exc)

    fingerprint = None
    try:
        experiments = session.get(
            f"{api_base.rstrip('/')}/experiments",
            headers=headers,
            timeout=20,
        )
        if experiments.status_code < 400:
            body = experiments.json()
            if isinstance(body, dict):
                fingerprint = str(body.get("fingerprint") or "").strip() or None
    except Exception as exc:
        logger.debug("discord experiments via curl_cffi failed: %s", exc)

    if fingerprint:
        headers["X-Fingerprint"] = fingerprint

    response = session.post(
        f"{api_base.rstrip('/')}/users/@me/remote-auth/login",
        headers=headers,
        json={"ticket": ticket},
        timeout=30,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}

    if response.status_code >= 400:
        message = _error_message(response.status_code, payload)
        logger.warning(
            "discord curl_cffi ticket exchange status=%s message=%s payload=%s",
            response.status_code,
            message,
            payload,
        )
        raise DiscordApiError(message, status_code=response.status_code, payload=payload)
    if not isinstance(payload, dict):
        raise DiscordApiError("unexpected remote-auth login response")
    return payload


def _exchange_remote_auth_ticket_sync(
    *,
    api_base: str,
    ticket: str,
    proxies: dict[str, str] | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    # Prefer direct first: shared TELEGRAM/http proxies are frequently captcha'd by Discord.
    # Then retry via the account proxy if one is configured.
    proxy_attempts: list[dict[str, str] | None] = [None]
    if proxies:
        proxy_attempts.append(proxies)

    last_error: DiscordApiError | None = None
    for attempt_proxies in proxy_attempts:
        proxy_url = _proxy_url(attempt_proxies)
        path_label = f"proxy={proxy_url.split('@')[-1] if proxy_url else 'direct'}"
        logger.info("discord remote-auth ticket exchange attempt %s", path_label)
        try:
            return _exchange_with_curl_cffi(
                api_base=api_base,
                ticket=ticket,
                proxy_url=proxy_url,
                user_agent=user_agent,
            )
        except DiscordApiError as exc:
            last_error = exc
            if exc.status_code in {400, 403} and attempt_proxies is None and proxies:
                logger.warning(
                    "discord remote-auth ticket exchange failed direct (%s); retrying proxy",
                    exc,
                )
                continue
            # Fall through to classic requests for this path.
        except Exception as exc:
            logger.warning("discord curl_cffi exchange failed (%s): %s", path_label, exc)
            last_error = DiscordApiError(str(exc) or "curl_cffi exchange failed")

        fingerprint = _fetch_fingerprint(
            api_base=api_base,
            proxies=attempt_proxies,
            user_agent=user_agent,
        )
        try:
            payload = _request(
                "POST",
                f"{api_base.rstrip('/')}/users/@me/remote-auth/login",
                json_body={"ticket": ticket},
                proxies=attempt_proxies,
                user_agent=user_agent,
                referer="https://discord.com/login",
                fingerprint=fingerprint,
            )
        except DiscordApiError as exc:
            last_error = exc
            if exc.status_code in {400, 403} and attempt_proxies is None and proxies:
                continue
            if attempt_proxies is not None or not proxies:
                raise
            continue
        if not isinstance(payload, dict):
            raise DiscordApiError("unexpected remote-auth login response")
        return payload

    assert last_error is not None
    raise last_error


async def exchange_remote_auth_ticket(
    *,
    api_base: str,
    ticket: str,
    proxies: dict[str, str] | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _exchange_remote_auth_ticket_sync,
        api_base=api_base,
        ticket=ticket,
        proxies=proxies,
        user_agent=user_agent,
    )


async def get_current_user(
    *,
    api_base: str,
    token: str,
    proxies: dict[str, str] | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
) -> dict[str, Any]:
    payload = await asyncio.to_thread(
        _request,
        "GET",
        f"{api_base.rstrip('/')}/users/@me",
        token=token,
        proxies=proxies,
        user_agent=user_agent,
    )
    if not isinstance(payload, dict):
        raise DiscordApiError("unexpected @me response")
    return payload

def display_name_from_user(user: dict[str, Any] | None) -> str:
    if not isinstance(user, dict):
        return ""
    global_name = str(user.get("global_name") or "").strip()
    if global_name:
        return global_name
    username = str(user.get("username") or "").strip()
    discriminator = str(user.get("discriminator") or "").strip()
    if username and discriminator and discriminator != "0":
        return f"{username}#{discriminator}"
    return username


def avatar_url_from_user(user: dict[str, Any] | None) -> str | None:
    if not isinstance(user, dict):
        return None
    user_id = str(user.get("id") or "").strip()
    avatar = str(user.get("avatar") or "").strip()
    if not user_id or not avatar:
        return None
    ext = "gif" if avatar.startswith("a_") else "png"
    return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}?size=128"

