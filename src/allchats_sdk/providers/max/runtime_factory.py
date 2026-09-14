from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pymax import Client, ExtraConfig, RegistrationConfig, WebClient
from pymax.protocol.enums import Command, Opcode
from pymax.protocol.models import InboundFrame
from pymax.types.domain import Message

from allchats_sdk.providers.max.media import (
    log_max_message_attachments,
    merge_strict_max_message,
    strict_max_message_valid,
    summarize_max_message,
    summarize_max_payload,
)
from allchats_sdk.providers.max.qr_auth_flow import WebQrAuthFlow
from allchats_sdk.providers.max.sms_auth_flow import WebSmsAuthFlow
from allchats_sdk.providers.max.timeutil import message_sent_at
from allchats_sdk.providers.max.providers import (
    WebPasswordProvider,
    WebQrHandler,
    WebSmsCodeProvider,
)
from allchats_sdk.providers.max.trace import max_trace
from allchats_sdk.providers.common.proxy import proxy_url_from_credentials
from allchats_sdk.config import Settings

if TYPE_CHECKING:
    from allchats_sdk.protocols import SessionManager, SessionRuntime

logger = logging.getLogger(__name__)


def _log_background_task_error(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        max_trace("background task failed name=%s", task.get_name())
        logger.exception("max background task failed name=%s", task.get_name())


class MaxRuntimeFactory:
    def __init__(self, settings: Settings, manager: SessionManager) -> None:
        self._settings = settings
        self._manager = manager

    def _extra_config(
        self,
        credentials: dict | None = None,
        *,
        reconnect: bool,
        token: str | None = None,
        registration_config: RegistrationConfig | None = None,
    ) -> ExtraConfig:
        creds = credentials or {}
        return ExtraConfig(
            log_level=self._settings.log_level,
            reconnect=reconnect,
            token=token if token is not None else (str(creds.get("auth_token") or "").strip() or None),
            device_id=str(creds.get("device_id") or "").strip() or None,
            mt_instance_id=str(creds.get("mt_instance_id") or "").strip() or None,
            proxy=proxy_url_from_credentials(creds),
            registration_config=registration_config,
        )

    async def start_phone(
        self,
        runtime: SessionRuntime,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> None:
        runtime.sms_provider = WebSmsCodeProvider(runtime, self._manager)
        runtime.password_provider = WebPasswordProvider(runtime, self._manager)

        extra_config = self._extra_config(
            reconnect=True,
            registration_config=RegistrationConfig(
                first_name=first_name,
                last_name=last_name or "",
            ) if first_name else None,
        )

        client = Client(
            phone=runtime.snapshot.phone or "",
            work_dir=str(self._settings.work_dir),
            session_name=runtime.snapshot.session_name,
            extra_config=extra_config,
            sms_code_provider=runtime.sms_provider,
            password_provider=runtime.password_provider,
        )
        runtime.client = client
        self._install_handlers(runtime)
        runtime.task = asyncio.create_task(
            self._run(runtime),
            name=f"max-phone-{runtime.snapshot.session_id[:8]}",
        )

    async def start_qr(self, runtime: SessionRuntime) -> None:
        runtime.qr_handler = WebQrHandler(runtime, self._manager)
        runtime.password_provider = WebPasswordProvider(runtime, self._manager)
        auth_flow = WebQrAuthFlow(
            runtime,
            self._manager,
            password_provider=runtime.password_provider,
        )
        client = WebClient(
            work_dir=str(self._settings.work_dir),
            session_name=runtime.snapshot.session_name,
            extra_config=self._extra_config(reconnect=False),
            auth_flow=auth_flow,
        )
        runtime.client = client
        self._install_handlers(runtime)
        runtime.task = asyncio.create_task(
            self._run(runtime),
            name=f"max-qr-{runtime.snapshot.session_id[:8]}",
        )

    async def start_from_account(self, runtime: SessionRuntime, credentials: dict) -> None:
        runtime.password_provider = WebPasswordProvider(runtime, self._manager)
        extra_config = self._extra_config(credentials, reconnect=True)
        phone = str(credentials.get("phone") or runtime.snapshot.phone or "").strip()

        if phone:
            runtime.sms_provider = WebSmsCodeProvider(runtime, self._manager)
            client = Client(
                phone=phone,
                work_dir=str(self._settings.work_dir),
                session_name=runtime.snapshot.session_name,
                extra_config=extra_config,
                sms_code_provider=runtime.sms_provider,
                password_provider=runtime.password_provider,
            )
        else:
            auth_flow = WebQrAuthFlow(
                runtime,
                self._manager,
                password_provider=runtime.password_provider,
            )
            client = WebClient(
                work_dir=str(self._settings.work_dir),
                session_name=runtime.snapshot.session_name,
                extra_config=extra_config,
                auth_flow=auth_flow,
            )

        runtime.client = client
        self._install_handlers(runtime)
        runtime.task = asyncio.create_task(
            self._run(runtime),
            name=f"max-account-{runtime.snapshot.session_id[:8]}",
        )

    async def start_phone_for_account(
        self,
        runtime: SessionRuntime,
        phone: str,
        credentials: dict,
    ) -> None:
        runtime.sms_provider = WebSmsCodeProvider(runtime, self._manager)
        runtime.password_provider = WebPasswordProvider(runtime, self._manager)
        auth_flow = WebSmsAuthFlow(
            runtime,
            self._manager,
            code_provider=runtime.sms_provider,
            password_provider=runtime.password_provider,
        )
        extra_config = self._extra_config(credentials, reconnect=False)
        client = Client(
            phone=phone,
            work_dir=str(self._settings.work_dir),
            session_name=runtime.snapshot.session_name,
            extra_config=extra_config,
            auth_flow=auth_flow,
            sms_code_provider=runtime.sms_provider,
            password_provider=runtime.password_provider,
        )
        runtime.client = client
        self._install_handlers(runtime)
        runtime.task = asyncio.create_task(
            self._run(runtime),
            name=f"max-phone-account-{runtime.snapshot.session_id[:8]}",
        )

    async def start_qr_for_account(self, runtime: SessionRuntime, credentials: dict) -> None:
        runtime.qr_handler = WebQrHandler(runtime, self._manager)
        runtime.password_provider = WebPasswordProvider(runtime, self._manager)
        auth_flow = WebQrAuthFlow(
            runtime,
            self._manager,
            password_provider=runtime.password_provider,
        )
        extra_config = self._extra_config(credentials, reconnect=False)
        client = WebClient(
            work_dir=str(self._settings.work_dir),
            session_name=runtime.snapshot.session_name,
            extra_config=extra_config,
            auth_flow=auth_flow,
        )
        runtime.client = client
        self._install_handlers(runtime)
        runtime.task = asyncio.create_task(
            self._run(runtime),
            name=f"max-account-qr-{runtime.snapshot.session_id[:8]}",
        )

    def _install_handlers(self, runtime: SessionRuntime) -> None:
        """Register pymax handlers once; router survives reconnects."""
        client = runtime.client
        if getattr(client, "_messager_max_handlers_installed", False):
            return

        original_reset = client._reset_runtime

        def reset_with_handlers() -> None:
            original_reset()

        client._reset_runtime = reset_with_handlers  # type: ignore[method-assign]
        self._register_handlers(runtime)
        client._messager_max_handlers_installed = True

    def _register_handlers(self, runtime: SessionRuntime) -> None:
        client = runtime.client
        session_id = runtime.snapshot.session_id
        processed_message_keys: set[tuple[int, int]] = set()

        logger.info("registering max message handlers session=%s", session_id[:8])
        max_trace("handlers registered session=%s", session_id[:8])

        def _mark_message_processed(chat_id: int, message_id: int) -> bool:
            key = (int(chat_id), int(message_id))
            if key in processed_message_keys:
                return True
            processed_message_keys.add(key)
            if len(processed_message_keys) > 4000:
                processed_message_keys.clear()
            return False

        async def _dispatch_max_message(
            message: Any,
            client: Client | WebClient,
            *,
            from_raw: bool,
        ) -> None:
            message_id = getattr(message, "id", None)
            if message_id is None:
                max_trace("skip message without id session=%s raw=%s", session_id[:8], from_raw)
                logger.warning(
                    "skip max message without id session=%s raw=%s",
                    session_id[:8],
                    from_raw,
                )
                return

            resolved_chat_id = await _resolve_message_chat_id(message, client)
            if resolved_chat_id is None:
                max_trace(
                    "skip message without chat_id session=%s msg=%s sender=%s raw=%s",
                    session_id[:8],
                    message_id,
                    getattr(message, "sender", None),
                    from_raw,
                )
                logger.warning(
                    "skip max message without chat_id session=%s msg=%s sender=%s raw=%s summary=%s",
                    session_id[:8],
                    message_id,
                    getattr(message, "sender", None),
                    from_raw,
                    summarize_max_message(message),
                )
                return
            message.chat_id = resolved_chat_id
            chat_id = resolved_chat_id

            if _mark_message_processed(int(chat_id), int(message_id)):
                max_trace(
                    "skip duplicate session=%s chat=%s msg=%s raw=%s",
                    session_id[:8],
                    chat_id,
                    message_id,
                    from_raw,
                )
                logger.info(
                    "skip max duplicate message session=%s chat=%s msg=%s raw=%s summary=%s",
                    session_id[:8],
                    chat_id,
                    message_id,
                    from_raw,
                    summarize_max_message(message),
                )
                return

            sender = getattr(message, "sender", None)
            is_incoming = self._is_incoming_message(runtime, sender)
            max_trace(
                "dispatch session=%s incoming=%s raw=%s %s",
                session_id[:8],
                is_incoming,
                from_raw,
                summarize_max_message(message),
            )
            logger.info(
                "max message dispatch session=%s incoming=%s raw=%s summary=%s",
                session_id[:8],
                is_incoming,
                from_raw,
                summarize_max_message(message),
            )
            log_max_message_attachments(message)

            await self._manager.publish_message(
                session_id,
                {
                    "type": "message",
                    "data": {
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "sender": sender,
                        "text": getattr(message, "text", ""),
                        "is_incoming": is_incoming,
                    },
                },
            )

            async def _process_incoming_message() -> None:
                try:
                    await self._manager.notify_incoming_message(
                        session_id,
                        chat_id=chat_id,
                        message_id=message_id,
                        sender=sender,
                        text=getattr(message, "text", ""),
                        sent_at=message_sent_at(message),
                        raw_message=message,
                        is_outgoing=not is_incoming,
                    )
                except Exception:
                    max_trace(
                        "handler failed session=%s chat=%s msg=%s",
                        session_id[:8],
                        chat_id,
                        message_id,
                    )
                    logger.exception(
                        "failed to handle incoming max message session=%s chat=%s",
                        session_id[:8],
                        chat_id,
                    )

            task = asyncio.create_task(
                _process_incoming_message(),
                name=f"max-incoming-{session_id[:8]}-{message_id}",
            )
            task.add_done_callback(_log_background_task_error)

        @client.on_start()
        async def on_start(_client: Client | WebClient) -> None:
            max_trace(
                "client connected session=%s account=%s me=%s",
                session_id[:8],
                (runtime.snapshot.account_id or "")[:8],
                getattr(getattr(getattr(_client, "me", None), "contact", None), "id", None),
            )
            logger.info(
                "max client on_start session=%s account=%s me=%s",
                session_id[:8],
                (runtime.snapshot.account_id or "")[:8],
                getattr(getattr(getattr(_client, "me", None), "contact", None), "id", None),
            )
            await self._manager.on_client_ready(session_id, _client)

        async def _resolve_message_chat_id(
            message: Any,
            client: Client | WebClient,
        ) -> int | None:
            chat_id = getattr(message, "chat_id", None)
            if chat_id is not None:
                try:
                    return int(chat_id)
                except (TypeError, ValueError):
                    return None

            sender = getattr(message, "sender", None)
            me = getattr(client, "me", None)
            contact = getattr(me, "contact", None) if me is not None else None
            me_id = getattr(contact, "id", None) if contact is not None else None
            sender_id: int | None = None
            me_int: int | None = None
            try:
                if sender is not None:
                    sender_id = int(sender)
                if me_id is not None:
                    me_int = int(me_id)
            except (TypeError, ValueError):
                sender_id = None
                me_int = None

            # Dialog chat ids are peer XOR me. Never XOR own sender with me (→ 0).
            if sender_id is not None and me_int is not None and sender_id != me_int:
                return sender_id ^ me_int

            message_id = getattr(message, "id", None)
            if message_id is not None:
                try:
                    want_id = int(message_id)
                except (TypeError, ValueError):
                    want_id = None
                if want_id is not None:
                    for chat in getattr(client, "chats", None) or []:
                        last = (
                            getattr(chat, "last_message", None)
                            or getattr(chat, "lastMessage", None)
                        )
                        last_id = getattr(last, "id", None) if last is not None else None
                        if last_id is None:
                            continue
                        try:
                            if int(last_id) != want_id:
                                continue
                        except (TypeError, ValueError):
                            continue
                        candidate = getattr(chat, "id", None)
                        if candidate is None:
                            continue
                        try:
                            return int(candidate)
                        except (TypeError, ValueError):
                            continue

            # Peer messages only: sender appears in exactly one dialog's participants.
            if sender_id is not None and (me_int is None or sender_id != me_int):
                for chat in getattr(client, "chats", None) or []:
                    participants = getattr(chat, "participants", None) or {}
                    if sender_id not in participants:
                        continue
                    candidate = getattr(chat, "id", None)
                    if candidate is not None:
                        try:
                            return int(candidate)
                        except (TypeError, ValueError):
                            continue
            return None

        @client.on_raw()
        async def on_raw(frame: InboundFrame, _client: Client | WebClient) -> None:
            if frame.opcode != int(Opcode.NOTIF_MESSAGE):
                return
            payload = frame.payload
            if not isinstance(payload, dict):
                return

            message_id = payload.get("id") or (payload.get("message") or {}).get("id")
            payload_summary = summarize_max_payload(payload)
            max_trace(
                "notif raw session=%s cmd=%s msg=%s %s",
                session_id[:8],
                frame.cmd,
                message_id,
                payload_summary,
            )
            logger.info(
                "max notif raw session=%s cmd=%s %s",
                session_id[:8],
                frame.cmd,
                payload_summary,
            )

            # Always parse here. pymax on_message only fires for flat REQUEST payloads;
            # nested / non-REQUEST frames would otherwise be dropped. Dedup in
            # _dispatch_max_message prevents double-handling when on_message also runs.
            message = merge_strict_max_message(payload)
            if message is None:
                if strict_max_message_valid(payload) and frame.cmd == int(Command.REQUEST):
                    logger.debug(
                        "max notif raw awaiting on_message session=%s msg=%s",
                        session_id[:8],
                        message_id,
                    )
                    return
                logger.warning(
                    "skip max raw: failed to parse message session=%s msg=%s %s",
                    session_id[:8],
                    message_id,
                    payload_summary,
                )
                return

            logger.info(
                "max notif raw dispatch session=%s summary=%s",
                session_id[:8],
                summarize_max_message(message),
            )
            log_max_message_attachments(message)
            await _dispatch_max_message(message, _client, from_raw=True)

        @client.on_message()
        async def on_message(message: Message, _client: Client | WebClient) -> None:
            summary = summarize_max_message(message)
            max_trace("notif message session=%s %s", session_id[:8], summary)
            logger.info(
                "max notif message session=%s summary=%s",
                session_id[:8],
                summary,
            )
            log_max_message_attachments(message)
            await _dispatch_max_message(message, _client, from_raw=False)

        @client.on_message_read()
        async def on_message_read(event: Any, _client: Client | WebClient) -> None:
            delivery_tracker = getattr(self._manager, "_delivery_tracker", None)
            account_id = runtime.snapshot.account_id
            if delivery_tracker is None or not account_id:
                return
            if getattr(event, "set_as_unread", False):
                return
            me = getattr(_client, "me", None)
            contact = getattr(me, "contact", None) if me is not None else None
            me_id = getattr(contact, "id", None) if contact is not None else None
            user_id = getattr(event, "user_id", None)
            if me_id is not None and user_id is not None:
                try:
                    if int(user_id) == int(me_id):
                        return
                except (TypeError, ValueError):
                    pass
            chat_id = getattr(event, "chat_id", None)
            mark = getattr(event, "mark", None)
            if chat_id is None or mark is None:
                return
            try:
                await delivery_tracker.mark_up_to_sent_at(
                    account_id,
                    external_chat_id=str(int(chat_id)),
                    sent_before=int(mark),
                    status="read",
                )
            except Exception:
                logger.exception(
                    "failed to apply max read receipt session=%s chat=%s",
                    session_id[:8],
                    chat_id,
                )

        @client.on_disconnect()
        async def on_disconnect(exc: Exception, reconnect: bool, delay: float) -> None:
            status = runtime.snapshot.status
            if status == "connected" and reconnect:
                await self._manager.set_status(session_id, "starting")
                return
            if status in ("waiting_qr", "waiting_sms", "waiting_password", "starting"):
                return
            await self._manager.set_status(session_id, "stopped", error=str(exc))

    @staticmethod
    def _is_incoming_message(runtime: SessionRuntime, sender: int | str | None) -> bool:
        """Return True for peer messages; False when sender is our account."""
        if sender is None:
            # Missing sender: treat as incoming rather than inventing direction.
            return True
        if runtime.client and runtime.client.me and runtime.client.me.contact:
            try:
                return int(sender) != int(runtime.client.me.contact.id)
            except (TypeError, ValueError):
                return True
        return True

    async def _run(self, runtime: SessionRuntime) -> None:
        session_id = runtime.snapshot.session_id
        account_id = (runtime.snapshot.account_id or "")[:8]
        try:
            logger.info(
                "max client starting session=%s account=%s",
                session_id[:8],
                account_id or "-",
            )
            max_trace("client starting session=%s account=%s", session_id[:8], account_id or "-")
            await self._manager.set_status(session_id, "starting")
            await runtime.client.start()
            logger.info("max client stopped session=%s account=%s", session_id[:8], account_id or "-")
        except asyncio.CancelledError:
            await self._manager.set_status(session_id, "stopped")
            raise
        except Exception as exc:
            logger.exception("max client failed session=%s", session_id[:8])
            if runtime.snapshot.auth_type == "qr":
                await self._manager.update_qr_watcher(
                    session_id,
                    login_available=False,
                    expires_at=0,
                    error=str(exc),
                )
            await self._manager.set_status(session_id, "error", error=str(exc))
