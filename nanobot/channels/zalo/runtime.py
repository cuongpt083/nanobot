"""Zalo personal-account channel using zca-js (OpenClaw zalouser protocol)."""

from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.zalo.client import ZaloBridge, ZaloBridgeError
from nanobot.channels.zalo.messages import (
    ZALO_TEXT_LIMIT,
    group_message_is_addressed,
    normalize_inbound_message,
)
from nanobot.channels.zalo.state import credentials_path_for, local_state_present, resolve_state_dir
from nanobot.config.schema import Base
from nanobot.utils.helpers import split_message


class ZaloConfig(Base):
    """Zalo channel configuration."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["mention", "open"] = "mention"
    state_dir: str = ""
    node_path: str = ""


class ZaloChannel(BaseChannel):
    """Zalo personal account via native zca-js integration."""

    name = "zalo"
    display_name = "Zalo"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return ZaloConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = ZaloConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: ZaloConfig = config
        self._bridge: ZaloBridge | None = None
        self._own_user_id = ""
        self._own_display_name = ""
        self._processed_ids: OrderedDict[str, None] = OrderedDict()
        self._event_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        self._qr_code = ""
        self._qr_image = ""
        self._qr_payload = ""
        self._login_error = ""
        self._logged_in = asyncio.Event()
        self._qr_ready = asyncio.Event()
        self._connect_login_task: asyncio.Task[dict[str, Any]] | None = None

    def _credentials_path(self) -> Path:
        if self.config.state_dir.strip():
            return resolve_state_dir({"stateDir": self.config.state_dir}) / "credentials.json"
        return credentials_path_for(self.config)

    def _new_bridge(self) -> ZaloBridge:
        return ZaloBridge(
            self._credentials_path(),
            node_path=self.config.node_path,
            on_event=self._on_bridge_event,
        )

    def _on_bridge_event(self, event: str, payload: dict[str, Any]) -> None:
        if event == "qr":
            self._qr_code = str(payload.get("code") or "").strip() or self._qr_code
            image = normalize_zalo_qr_image(str(payload.get("image") or ""))
            if image:
                self._qr_image = image
                self._qr_ready.set()
            decoded = str(payload.get("payload") or "").strip()
            if decoded:
                self._qr_payload = decoded
        elif event == "qr_declined":
            self._login_error = "QR login was declined on the phone."
            self._logged_in.set()
        elif event == "qr_expired":
            self._login_error = "QR code expired. Start login again."
            self._logged_in.set()
        elif event == "login_ok":
            self._own_user_id = str(payload.get("userId") or "").strip()
            self._login_error = ""
            self._logged_in.set()
        self._event_queue.put_nowait((event, payload))

    def _print_login_qr(self) -> None:
        self.logger.info("Scan this QR with the Zalo app on your phone")
        image_path = self._write_official_qr_image()
        text = self._qr_payload.strip()
        if not text:
            if image_path is not None:
                self.logger.info(
                    "Open {} and scan it with Zalo. The session id is not a login QR.",
                    image_path,
                )
            return
        try:
            import segno  # pyright: ignore[reportMissingImports]

            make_qr = getattr(segno, "make_qr", None)
            if not callable(make_qr):
                raise RuntimeError("segno.make_qr is unavailable")
            printer = getattr(make_qr(text), "terminal", None)
            if callable(printer):
                printer(compact=True)
            else:
                self.logger.info("QR payload: {}", text)
        except Exception:
            if image_path is not None:
                self.logger.info("Scan the official QR image at {}", image_path)
            else:
                self.logger.info("QR payload: {}", text)

    def _write_official_qr_image(self) -> Path | None:
        if not self._qr_image:
            return None
        try:
            raw = self._qr_image.split(",", 1)[-1]
            path = self._credentials_path().parent / "login-qr.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(base64.b64decode(raw))
            self.logger.info("Official Zalo QR image saved at {}", path)
            return path
        except Exception:
            return None

    async def _ensure_bridge(self) -> ZaloBridge:
        if self._bridge is not None and self._bridge.running:
            return self._bridge
        bridge = self._new_bridge()
        await bridge.start()
        self._bridge = bridge
        return bridge

    async def login(self, force: bool = False) -> bool:
        """QR-login a personal Zalo account and persist zca-js credentials."""
        try:
            if not force and local_state_present(self.config):
                bridge = await self._ensure_bridge()
                result = await bridge.call("login_session")
                self._own_user_id = str(result.get("userId") or "").strip()
                self.logger.info("Zalo session restored (userId={})", self._own_user_id or "unknown")
                await bridge.stop()
                self._bridge = None
                return True

            if force:
                with suppress(Exception):
                    bridge = await self._ensure_bridge()
                    await bridge.call("logout")
                    await bridge.stop()
                    self._bridge = None

            self._qr_code = ""
            self._qr_image = ""
            self._qr_payload = ""
            self._login_error = ""
            self._logged_in = asyncio.Event()
            self._qr_ready = asyncio.Event()
            bridge = await self._ensure_bridge()
            login_task = asyncio.create_task(bridge.call("login_qr", timeout=180))
            try:
                await asyncio.wait_for(self._qr_ready.wait(), timeout=30)
            except TimeoutError:
                if not login_task.done():
                    with suppress(Exception):
                        await bridge.call("abort_qr", timeout=5)
                    login_task.cancel()
                self.logger.error("Timed out waiting for a Zalo QR code")
                return False
            for _ in range(20):
                if self._qr_payload:
                    break
                await asyncio.sleep(0.05)
            self._print_login_qr()
            try:
                result = await login_task
            except ZaloBridgeError as exc:
                self.logger.error("Zalo QR login failed: {}", exc)
                return False
            if self._login_error:
                self.logger.error("{}", self._login_error)
                return False
            self._own_user_id = str(result.get("userId") or self._own_user_id).strip()
            self.logger.info("Zalo login complete (userId={})", self._own_user_id or "unknown")
            return True
        except ZaloBridgeError as exc:
            self.logger.error("{}", exc)
            return False
        finally:
            if self._bridge is not None:
                with suppress(Exception):
                    await self._bridge.stop()
                self._bridge = None

    async def start(self) -> None:
        self._running = True
        try:
            bridge = await self._ensure_bridge()
            result = await bridge.call("login_session")
            self._own_user_id = str(result.get("userId") or "").strip()
            await bridge.call("listen")
            self.logger.info("Zalo channel listening (userId={})", self._own_user_id or "unknown")
            while self._running:
                event, payload = await self._event_queue.get()
                if event == "message":
                    await self._handle_inbound(payload)
                elif event in {"error", "closed"}:
                    message = str(payload.get("message") or payload.get("reason") or event)
                    self.logger.warning("Zalo listener {}: {}", event, message)
                    if event == "closed" and self._running:
                        raise ZaloBridgeError(f"Zalo listener closed: {message}")
        except asyncio.CancelledError:
            raise
        except ZaloBridgeError as exc:
            self.logger.error(
                "{}. Run 'nanobot channels login zalo' to authenticate.",
                exc,
            )
            raise
        finally:
            self._running = False
            if self._bridge is not None:
                with suppress(Exception):
                    await self._bridge.stop()
                self._bridge = None

    async def stop(self) -> None:
        self._running = False
        if self._bridge is not None:
            with suppress(Exception):
                await self._bridge.stop()
            self._bridge = None

    async def send(self, msg: OutboundMessage) -> None:
        bridge = self._bridge
        if bridge is None or not bridge.running:
            raise RuntimeError("Zalo channel is not connected")
        is_group = self._chat_is_group(msg.chat_id, msg.metadata)
        thread_id = self._thread_id(msg.chat_id)
        with suppress(Exception):
            await bridge.call(
                "typing",
                {"threadId": thread_id, "isGroup": is_group},
                timeout=10,
            )
        chunks = split_message(msg.content or "", ZALO_TEXT_LIMIT)
        attachments = self._local_attachments(msg.media)
        if not chunks and attachments:
            chunks = [""]
        for index, chunk in enumerate(chunks):
            params: dict[str, Any] = {
                "threadId": thread_id,
                "isGroup": is_group,
                "text": chunk,
            }
            if index == 0 and attachments:
                params["attachments"] = attachments
            await bridge.call("send", params)

    def start_error_message(self, error: Exception) -> str | None:
        if isinstance(error, ZaloBridgeError):
            return str(error)
        return None

    async def connect_start_qr(self, *, force: bool = False) -> str:
        """Start QR login for the WebUI connector and return the official QR image."""
        if not force and local_state_present(self.config):
            return ""
        self._qr_code = ""
        self._qr_image = ""
        self._qr_payload = ""
        self._login_error = ""
        self._logged_in = asyncio.Event()
        self._qr_ready = asyncio.Event()
        if force and local_state_present(self.config):
            with suppress(Exception):
                bridge = await self._ensure_bridge()
                await bridge.call("logout")
        bridge = await self._ensure_bridge()
        self._connect_login_task = asyncio.create_task(bridge.call("login_qr", timeout=180))
        try:
            await asyncio.wait_for(self._qr_ready.wait(), timeout=30)
        except TimeoutError as exc:
            await self.connect_cancel()
            raise ZaloBridgeError("Timed out waiting for a Zalo QR code") from exc
        return self._qr_image

    async def connect_poll_qr(self) -> dict[str, Any]:
        if self._login_error:
            return {"status": "failed", "message": self._login_error}
        task = self._connect_login_task
        if isinstance(task, asyncio.Task) and task.done():
            if task.cancelled():
                return {"status": "failed", "message": "Zalo login cancelled."}
            exc = task.exception()
            if exc is not None:
                return {"status": "failed", "message": str(exc)}
            result = task.result()
            self._own_user_id = str(result.get("userId") or "").strip()
            return {
                "status": "succeeded",
                "message": "Zalo is connected.",
                "account": self._own_user_id,
            }
        if self._logged_in.is_set() and not self._login_error:
            return {
                "status": "succeeded",
                "message": "Zalo is connected.",
                "account": self._own_user_id,
            }
        return {"status": "pending", "qr_url": self._qr_image}

    async def connect_cancel(self) -> None:
        task = self._connect_login_task
        if self._bridge is not None:
            with suppress(Exception):
                await self._bridge.call("abort_qr", timeout=5)
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self._bridge is not None:
            with suppress(Exception):
                await self._bridge.stop()
            self._bridge = None

    async def connect_close(self) -> None:
        await self.connect_cancel()

    async def _handle_inbound(self, payload: dict[str, Any]) -> None:
        inbound = normalize_inbound_message(payload, self._own_user_id)
        if inbound is None:
            return
        if inbound.msg_id:
            if inbound.msg_id in self._processed_ids:
                return
            self._processed_ids[inbound.msg_id] = None
            while len(self._processed_ids) > 1000:
                self._processed_ids.popitem(last=False)
        if inbound.is_group and self.config.group_policy == "mention":
            if not group_message_is_addressed(inbound, self._own_display_name):
                return
        if not inbound.content and not inbound.media:
            return
        metadata: dict[str, Any] = {
            "is_group": inbound.is_group,
            "sender_name": inbound.sender_name,
        }
        if inbound.group_name:
            metadata["group_name"] = inbound.group_name
        if inbound.msg_id:
            metadata["message_id"] = inbound.msg_id
        await self._handle_message(
            sender_id=inbound.sender_id,
            chat_id=inbound.thread_id,
            content=inbound.content,
            media=list(inbound.media),
            metadata=metadata,
            is_dm=not inbound.is_group,
        )

    @staticmethod
    def _thread_id(chat_id: str) -> str:
        value = chat_id.strip()
        if value.startswith("group:"):
            return value.split(":", 1)[1]
        return value

    @staticmethod
    def _chat_is_group(chat_id: str, metadata: dict[str, Any] | None) -> bool:
        if metadata and bool(metadata.get("is_group")):
            return True
        return chat_id.startswith("group:")

    @staticmethod
    def _local_attachments(media: list[str] | None) -> list[dict[str, str]]:
        attachments: list[dict[str, str]] = []
        for item in media or []:
            raw = item.strip()
            if not raw or raw.startswith(("http://", "https://", "data:")):
                continue
            path = Path(urlparse(raw).path if "://" in raw else raw).expanduser()
            if path.is_file():
                attachments.append({"path": str(path)})
        return attachments


def normalize_zalo_qr_image(image: str) -> str:
    raw = image.strip()
    if not raw:
        return ""
    if raw.startswith("data:image"):
        return raw
    return f"data:image/png;base64,{raw}"
