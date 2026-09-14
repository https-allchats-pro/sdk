from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from allchats_sdk.providers.avito.client import (
    AvitoApiError,
    delete_chat_message,
    get_subscriptions,
    get_token_authorization_code,
    get_token_client_credentials,
    get_user_info,
    refresh_access_token,
    send_chat_message,
    subscribe_webhook,
    token_expires_at_ms,
    user_avatar_from_info,
)
from allchats_sdk.providers.avito.sync_worker import (
    handle_avito_webhook_payload,
    run_avito_sync_worker,
)
from allchats_sdk.providers.common.proxy import requests_proxies_from_credentials
from allchats_sdk.config import Settings
from allchats_sdk.events import CredentialsUpdatedEvent, OutgoingMessageEvent
from allchats_sdk.protocols import EventSink, IncomingMessageHandler, MediaStorage
from allchats_sdk.providers.credentials_cache import CredentialsCache
from allchats_sdk.credentials import (
    avito_authorized,
    merge_credentials,
)
from allchats_sdk.errors import ValidationError
from allchats_sdk.internal.observability import record_auth

logger = logging.getLogger(__name__)

AVITO_NOT_CONFIGURED = "avito client_id and client_secret are not configured"


@dataclass
class AvitoAccountClient:
    account_id: str
    state_instance: str = "starting"
    user_id: str = ""
    running: bool = False
    stop_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False, compare=False)


class AvitoClientManager:
    def __init__(
        self,
        settings: Settings,
        event_sink: EventSink,
        incoming_handler: IncomingMessageHandler | None = None,
    ) -> None:
        self._settings = settings
        self._sink = event_sink
        self._creds = CredentialsCache()
        self._incoming_handler = incoming_handler
        self._clients: dict[str, AvitoAccountClient] = {}
        self._sync_tasks: dict[str, asyncio.Task[None]] = {}
        self._media_storage: MediaStorage | None = None

    @property
    def event_sink(self) -> EventSink:
        return self._sink

    def is_configured(self) -> bool:
        return self._settings.avito.is_configured()

    def oauth_redirect_uri(self) -> str:
        return self._settings.avito.redirect_uri.strip()

    def oauth_client_id(self) -> str:
        return self._settings.avito.client_id.strip()

    def oauth_client_secret(self) -> str:
        return self._settings.avito.client_secret.strip()

    def requests_proxies(self, credentials: dict[str, Any]) -> dict[str, str] | None:
        return requests_proxies_from_credentials(credentials)

    def client_for_account(self, account_id: str) -> AvitoAccountClient | None:
        return self._clients.get(account_id)

    def connected_count(self) -> int:
        return len(self._clients)

    def unregister_client(self, account_id: str) -> None:
        self._clients.pop(account_id, None)

    def set_client_state(
        self,
        account_id: str,
        *,
        state_instance: str,
        user_id: str = "",
        running: bool = False,
    ) -> AvitoAccountClient:
        client = self._clients.get(account_id)
        if client is None:
            client = AvitoAccountClient(account_id=account_id)
            self._clients[account_id] = client
        client.state_instance = state_instance
        client.user_id = user_id or client.user_id
        client.running = running
        return client

    async def connect_with_keys(
        self,
        account_id: str,
        *,
        client_id: str,
        client_secret: str,
    ) -> dict[str, Any]:
        try:
            client_id = client_id.strip()
            client_secret = client_secret.strip()
            if not client_id or not client_secret:
                raise ValidationError("client_id and client_secret are required")

            proxies = self.requests_proxies(self._creds.get_or_empty(account_id))

            token_response = await get_token_client_credentials(
                client_id=client_id,
                client_secret=client_secret,
                proxies=proxies,
            )
            return await self._persist_token_response(
                account_id,
                token_response,
                auth_method="keys",
                client_id=client_id,
                client_secret=client_secret,
            )
        except ValidationError:
            record_auth("avito", "failed")
            raise
        except Exception:
            record_auth("avito", "failed")
            raise

    async def connect_with_oauth_code(
        self,
        account_id: str,
        *,
        code: str,
    ) -> dict[str, Any]:
        if not self.is_configured():
            raise ValidationError(AVITO_NOT_CONFIGURED)

        redirect_uri = self.oauth_redirect_uri()
        if not redirect_uri:
            raise ValidationError("avito redirect_uri is not configured")

        proxies = self.requests_proxies(self._creds.get_or_empty(account_id))

        token_response = await get_token_authorization_code(
            client_id=self.oauth_client_id(),
            client_secret=self.oauth_client_secret(),
            code=code.strip(),
            redirect_uri=redirect_uri,
            proxies=proxies,
        )
        return await self._persist_token_response(
            account_id,
            token_response,
            auth_method="oauth",
            client_id=self.oauth_client_id(),
            client_secret="",
        )

    async def ensure_valid_token(self, account_id: str, credentials: dict[str, Any]) -> dict[str, Any]:
        if not avito_authorized(credentials):
            raise ValidationError("account is not authorized")

        proxies = self.requests_proxies(credentials)
        expires_at = int(credentials.get("token_expires_at") or 0)
        now_ms = int(time.time() * 1000)
        if credentials.get("access_token") and expires_at > now_ms + 60_000:
            return credentials

        refresh_token = str(credentials.get("refresh_token") or "").strip()
        client_id = str(credentials.get("client_id") or "").strip()
        client_secret = str(credentials.get("client_secret") or "").strip()

        if credentials.get("auth_method") == "oauth" and self.is_configured():
            client_id = self.oauth_client_id()
            client_secret = self.oauth_client_secret()

        if refresh_token and client_id and client_secret:
            token_response = await refresh_access_token(
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                proxies=proxies,
            )
            return await self._persist_token_response(
                account_id,
                token_response,
                auth_method=str(credentials.get("auth_method") or "oauth"),
                client_id=client_id,
                client_secret=client_secret if credentials.get("auth_method") == "keys" else "",
                existing=credentials,
                restart_sync=False,
            )

        if credentials.get("auth_method") == "keys" and client_id and client_secret:
            token_response = await get_token_client_credentials(
                client_id=client_id,
                client_secret=client_secret,
                proxies=proxies,
            )
            return await self._persist_token_response(
                account_id,
                token_response,
                auth_method="keys",
                client_id=client_id,
                client_secret=client_secret,
                existing=credentials,
                restart_sync=False,
            )

        raise ValidationError("avito token expired and cannot be refreshed")

    async def get_sync_credentials(self, account_id: str) -> dict[str, Any]:
        return await self.ensure_valid_token(account_id, self._creds.get(account_id))

    async def _persist_token_response(
        self,
        account_id: str,
        token_response: dict[str, Any],
        *,
        auth_method: str,
        client_id: str,
        client_secret: str,
        existing: dict[str, Any] | None = None,
        restart_sync: bool = True,
    ) -> dict[str, Any]:
        access_token = str(token_response.get("access_token") or "").strip()
        if not access_token:
            raise ValidationError("avito token response missing access_token")

        merged_existing = existing or {"device_id": account_id}
        proxies = self.requests_proxies(merged_existing)

        try:
            user_info = await get_user_info(access_token, proxies=proxies)
        except AvitoApiError as exc:
            raise ValidationError(f"failed to verify avito token: {exc}") from exc

        user_id = str(user_info.get("id") or user_info.get("user_id") or "").strip()
        nickname = _extract_nickname(user_info)
        avatar_url = user_avatar_from_info(user_info)

        incoming: dict[str, Any] = {
            "auth_method": auth_method,
            "client_id": client_id,
            "access_token": access_token,
            "refresh_token": str(token_response.get("refresh_token") or "").strip(),
            "token_expires_at": token_expires_at_ms(token_response),
            "user_id": user_id,
            "device_id": account_id,
        }
        if avatar_url:
            incoming["avatar_url"] = avatar_url
        if auth_method == "keys" and client_secret:
            incoming["client_secret"] = client_secret
        elif auth_method == "oauth":
            incoming.pop("client_secret", None)

        if restart_sync:
            incoming["sync_started_at"] = int(time.time() * 1000)

        merged = merge_credentials(existing or {"device_id": account_id}, incoming)
        self._creds.set(account_id, merged)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="avito",
                credentials=merged,
                user_id=user_id,
                nickname=nickname,
            )
        )
        if restart_sync:
            await self.ensure_sync(account_id, merged)
            record_auth("avito", "success")
        return merged

    async def ensure_sync(
        self,
        account_id: str,
        credentials: dict[str, Any] | None = None,
    ) -> AvitoAccountClient:
        if credentials is None:
            credentials = self._creds.get_or_empty(account_id)

        credentials = await self.ensure_valid_token(account_id, credentials or {})
        self._creds.set(account_id, credentials)
        if not avito_authorized(credentials):
            return self.set_client_state(
                account_id,
                state_instance="notAuthorized",
                running=False,
            )

        existing_task = self._sync_tasks.get(account_id)
        if existing_task is not None and not existing_task.done():
            return self.set_client_state(
                account_id,
                state_instance="authorized",
                user_id=str(credentials.get("user_id") or ""),
                running=True,
            )

        await self.stop_sync(account_id)

        user_id = str(credentials.get("user_id") or "").strip()
        client = self.set_client_state(
            account_id,
            state_instance="authorized",
            user_id=user_id,
            running=True,
        )
        client.stop_event = asyncio.Event()

        await self._ensure_webhook(account_id, credentials)

        poll_interval = max(5, int(self._settings.avito.poll_interval_sec or 15))
        self._sync_tasks[account_id] = asyncio.create_task(
            run_avito_sync_worker(
                account_id,
                manager=self,
                event_sink=self._sink,
                poll_interval_sec=float(poll_interval),
                stop_event=client.stop_event,
            ),
            name=f"avito-sync-{account_id[:8]}",
        )
        return client

    async def _ensure_webhook(self, account_id: str, credentials: dict[str, Any]) -> None:
        if not self._settings.avito.webhook_configured():
            return

        access_token = str(credentials.get("access_token") or "").strip()
        if not access_token:
            return

        proxies = self.requests_proxies(credentials)
        base_url = self._settings.avito.webhook_base_url.rstrip("/")
        secret = quote(self._settings.avito.webhook_secret.strip(), safe="")
        webhook_url = f"{base_url}/avito/webhook/{account_id}?token={secret}"

        try:
            subscriptions = await get_subscriptions(access_token, proxies=proxies)
            for item in subscriptions.get("subscriptions") or []:
                if isinstance(item, dict) and str(item.get("url") or "").strip() == webhook_url:
                    return
        except AvitoApiError:
            logger.debug("avito get subscriptions failed account=%s", account_id[:8], exc_info=True)

        try:
            await subscribe_webhook(url=webhook_url, access_token=access_token, proxies=proxies)
            logger.info("avito webhook subscribed account=%s", account_id[:8])
        except AvitoApiError as exc:
            logger.warning("avito webhook subscribe failed account=%s: %s", account_id[:8], exc)

    async def stop_sync(self, account_id: str) -> None:
        client = self._clients.get(account_id)
        if client is not None:
            client.stop_event.set()
            client.running = False

        task = self._sync_tasks.pop(account_id, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("avito sync task cleanup failed account=%s: %s", account_id[:8], exc)

    async def disconnect(self, account_id: str) -> None:
        await self.stop_sync(account_id)
        await self._sink.on_credentials_updated(
            CredentialsUpdatedEvent(
                connection_id=account_id,
                provider="avito",
                credentials={},
                clear=True,
            )
        )
        self._creds.pop(account_id)
        self.unregister_client(account_id)

    async def connect_account(
        self,
        account_id: str,
        credentials: dict[str, Any],
    ) -> AvitoAccountClient:
        if not avito_authorized(credentials):
            raise ValidationError("account is not authorized")
        self._creds.set(account_id, credentials)
        return await self.ensure_sync(account_id, credentials)

    async def handle_webhook(
        self,
        account_id: str,
        payload: dict[str, Any],
    ) -> None:
        await handle_avito_webhook_payload(
            account_id,
            payload,
            manager=self,
            event_sink=self._sink,
        )

    async def send_message(
        self,
        account_id: str,
        *,
        text: str,
        chat_id: str,
    ) -> tuple[str, str]:
        trimmed = text.strip()
        if not trimmed:
            raise ValidationError("text is required")
        if not chat_id.strip():
            raise ValidationError("chat_id is required")

        credentials = await self.ensure_valid_token(account_id, self._creds.get(account_id))
        user_id = str(credentials.get("user_id") or "").strip()
        access_token = str(credentials.get("access_token") or "").strip()
        if not user_id or not access_token:
            raise ValidationError("avito account is not authorized")

        external_chat_id = chat_id.strip()
        try:
            response = await send_chat_message(
                user_id=user_id,
                chat_id=external_chat_id,
                access_token=access_token,
                text=trimmed,
                proxies=self.requests_proxies(credentials),
            )
        except AvitoApiError as exc:
            if exc.status == 402:
                raise ValidationError(
                    "Avito messenger API subscription required to send messages"
                ) from exc
            raise ValidationError(f"failed to send avito message: {exc}") from exc

        message_id = str(
            response.get("id")
            or response.get("message_id")
            or (response.get("message") or {}).get("id")
            or uuid.uuid4().hex
        )
        await self._sink.on_outgoing(
            OutgoingMessageEvent(
                connection_id=account_id,
                provider="avito",
                external_chat_id=external_chat_id,
                external_message_id=message_id,
                text=trimmed,
                from_id=user_id,
                sent_at=datetime.now(UTC),
            )
        )
        return message_id, external_chat_id

    async def delete_message(
        self,
        account_id: str,
        *,
        chat_id: str,
        external_message_id: str,
    ) -> None:
        credentials = await self.ensure_valid_token(account_id, self._creds.get(account_id))
        user_id = str(credentials.get("user_id") or "").strip()
        access_token = str(credentials.get("access_token") or "").strip()
        if not user_id or not access_token:
            raise ValidationError("avito account is not authorized")

        external_chat_id = chat_id.strip()
        try:
            await delete_chat_message(
                user_id=user_id,
                chat_id=external_chat_id,
                message_id=external_message_id,
                access_token=access_token,
                proxies=self.requests_proxies(credentials),
            )
        except AvitoApiError as exc:
            raise ValidationError(f"failed to delete avito message: {exc}") from exc


def _extract_nickname(user_info: dict[str, Any]) -> str | None:
    name = str(user_info.get("name") or "").strip()
    if name:
        return name

    email = str(user_info.get("email") or "").strip()
    if email:
        return email

    profile = user_info.get("profile")
    if isinstance(profile, dict):
        profile_name = str(profile.get("name") or "").strip()
        if profile_name:
            return profile_name
    return None
