from __future__ import annotations

import asyncio
import logging

from allchats_sdk.providers.vk.manager import VkAccountClient, VkClientManager
from allchats_sdk.providers.vk.qr_auth import (
    POLL_INTERVAL_SEC,
    QrStatus,
    VkQrAuthError,
    check_auth_code_async,
    init_qr_session_async,
    resolve_approved_token_async,
)
from allchats_sdk.internal.observability import record_auth

logger = logging.getLogger(__name__)


async def run_vk_qr_auth_worker(
    account_id: str,
    *,
    manager: VkClientManager,
    client: VkAccountClient,
    proxies: dict[str, str] | None = None,
) -> None:
    try:
        manager.set_client_state(account_id, state_instance="qrWaiting", running=True)
        auth_url, auth_hash, anonym_token = await init_qr_session_async(proxies=proxies)
        client.auth_url = auth_url
        client.qr_status = QrStatus.CREATED.name.lower()
        client.state_instance = "qrWaiting"

        while client.running:
            await asyncio.sleep(POLL_INTERVAL_SEC)
            result = await check_auth_code_async(anonym_token, auth_hash, proxies=proxies)
            status = QrStatus(result["status"])
            client.qr_status = status.name.lower()

            if status in (QrStatus.CREATED, QrStatus.OPENED):
                continue

            if status == QrStatus.APPROVED:
                access_token, _user_id = await resolve_approved_token_async(
                    result,
                    anonym_token,
                    auth_hash,
                    proxies=proxies,
                )
                await manager.connect_with_token(
                    account_id,
                    access_token=access_token,
                    auth_method="qr",
                )
                return

            if status == QrStatus.DECLINED:
                raise VkQrAuthError("Вход отклонён в приложении VK")

            if status == QrStatus.EXPIRED:
                raise VkQrAuthError("QR-код истёк")

            raise VkQrAuthError(f"Неизвестный статус QR: {status}")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("vk qr auth failed account=%s: %s", account_id[:8], exc)
        manager.set_client_state(
            account_id,
            state_instance="notAuthorized",
            error=str(exc),
            running=False,
        )
        record_auth("vk", "failed")
        raise
    finally:
        manager.cleanup_qr_auth(account_id)
