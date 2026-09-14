"""MAX transport helpers (pymax client construction).

Not the public ``allchats_sdk.clients.MAXClient`` facade.
Session orchestration stays on the host ``SessionManager`` + ``MaxRuntimeFactory``.
"""

from __future__ import annotations

from typing import Any

from pymax import ExtraConfig, RegistrationConfig

from allchats_sdk.providers.common.proxy import proxy_url_from_credentials

__all__ = ["build_extra_config"]


def build_extra_config(
    credentials: dict[str, Any] | None = None,
    *,
    log_level: str = "INFO",
    reconnect: bool,
    token: str | None = None,
    registration_config: RegistrationConfig | None = None,
) -> ExtraConfig:
    creds = credentials or {}
    return ExtraConfig(
        log_level=log_level,
        reconnect=reconnect,
        token=token if token is not None else (str(creds.get("auth_token") or "").strip() or None),
        device_id=str(creds.get("device_id") or "").strip() or None,
        mt_instance_id=str(creds.get("mt_instance_id") or "").strip() or None,
        proxy=proxy_url_from_credentials(creds),
        registration_config=registration_config,
    )
