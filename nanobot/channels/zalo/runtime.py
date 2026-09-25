"""Zalo channel implementation using a WebSocket bridge sidecar."""

from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
from typing import Any, Literal, cast
from uuid import uuid4

import httpx
import websockets
from loguru import logger
from pydantic import Field
from websockets.asyncio.client import ClientConnection

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.zalo.zalo_formatter import (
    format_and_split_for_zalo,
)
from nanobot.config.paths import get_media_dir
from nanobot.config_base import Base
from nanobot.utils.helpers import safe_filename

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


class ZaloConfig(Base):
    """Zalo channel configuration."""

    enabled: bool = False
    bridge_url: str = "ws://127.0.0.1:3002"
    bridge_token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "mention", "allowlist"] = "mention"
    group_allow_from: list[str] = Field(default_factory=list)
    bot_user_id: str = Field(
        default="",
        description="Zalo UID of the bot account. Auto-detected from bridge, but can be manually set.",
    )
    bot_name: str = Field(
        default="",
        description="Display name or alias of the bot for text @name mentions in group chat.",
    )
    reply_with_quote: bool = True


class ZaloChannel(BaseChannel):
    """Zalo channel connecting to a zca-js WebSocket bridge."""

    name: str = "zalo"
    display_name: str = "Zalo"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return ZaloConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus) -> None:
        if isinstance(config, dict):
            config = ZaloConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: ZaloConfig = config
        self._ws: ClientConnection | Any = None
        self._connected: bool = False
        self._bot_user_id: str = ""
        self._bot_display_name: str = ""
        self.last_error_status: str = ""
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()
        self._typing_tasks: dict[str, asyncio.Task[None]] = {}
        self._chat_thread_types: OrderedDict[str, str] = OrderedDict()
        self._last_chat_message_ids: OrderedDict[str, str] = OrderedDict()
        self._http: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """Start the Zalo channel by connecting to the WebSocket bridge."""
        self._running = True
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        bridge_url = self.config.bridge_url
        logger.info("Connecting to Zalo bridge at {}...", bridge_url)

        backoff = 1.0
        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    if self.config.bridge_token:
                        await ws.send(
                            json.dumps(
                                {"type": "auth", "token": self.config.bridge_token},
                                ensure_ascii=False,
                            )
                        )
                    # Request current bridge status and bot identity
                    await ws.send(json.dumps({"type": "get_status"}, ensure_ascii=False))
                    self._connected = True
                    self.last_error_status = ""
                    backoff = 1.0
                    logger.info("Connected to Zalo bridge")

                    async for raw_msg in ws:
                        try:
                            await self._handle_bridge_message(str(raw_msg))
                        except Exception as e:
                            logger.error("Error handling Zalo bridge message: {}", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning("Zalo bridge connection error: {}", e)

                if self._running:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, 10.0)

    async def stop(self) -> None:
        """Stop the Zalo channel."""
        self._running = False
        self._connected = False
        for task in list(self._typing_tasks.values()):
            task.cancel()
        self._typing_tasks.clear()
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _download_attachments(
        self, attachments: list[dict[str, Any]]
    ) -> list[str]:
        """Download incoming attachments to this channel's media dir."""
        if not attachments or not self._http:
            return []

        media_dir = get_media_dir("zalo")
        media_dir.mkdir(parents=True, exist_ok=True)
        media_paths: list[str] = []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://chat.zalo.me/",
        }

        for att in attachments:
            url = att.get("url")
            if not url or not isinstance(url, str):
                continue
            if not (url.startswith("http://") or url.startswith("https://")):
                continue

            size = att.get("size")
            if (
                size
                and isinstance(size, (int, float))
                and size > MAX_ATTACHMENT_BYTES
            ):
                logger.warning(
                    "Skipping oversized Zalo attachment: {} ({} bytes)", url, size
                )
                continue

            raw_filename = att.get("filename")
            filename = (
                safe_filename(raw_filename if isinstance(raw_filename, str) else "attachment")
                or "attachment"
            )
            file_path = media_dir / f"{uuid4().hex[:12]}_{filename}"

            try:
                resp = await self._http.get(url, headers=headers)
                resp.raise_for_status()
                if len(resp.content) > MAX_ATTACHMENT_BYTES:
                    logger.warning(
                        "Downloaded Zalo attachment exceeded size cap: {}", url
                    )
                    continue
                file_path.write_bytes(resp.content)
                media_paths.append(str(file_path))
            except Exception as e:
                logger.warning(
                    "Failed to download Zalo attachment from {}: {}", url, e
                )

        return media_paths

    def _start_typing(self, chat_id: str, thread_type: str = "user") -> None:
        """Start sending periodic typing indicator for a chat."""
        self._stop_typing(chat_id)
        raw_thread_id = (
            chat_id.removeprefix("group:") if chat_id.startswith("group:") else chat_id
        )
        self._typing_tasks[chat_id] = asyncio.create_task(
            self._typing_loop(raw_thread_id, thread_type)
        )

    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        raw_id = (
            chat_id.removeprefix("group:") if chat_id.startswith("group:") else chat_id
        )
        for key in (chat_id, raw_id, f"group:{raw_id}"):
            task = self._typing_tasks.pop(key, None)
            if task and not task.done():
                task.cancel()

    async def _typing_loop(self, chat_id: str, thread_type: str) -> None:
        """Periodically send typing indicator to Zalo until stopped or timed out."""
        elapsed = 0.0
        try:
            while elapsed < 120.0:
                if self._ws and self._connected:
                    payload = {
                        "type": "typing",
                        "thread_id": chat_id,
                        "thread_type": thread_type,
                    }
                    await self._ws.send(json.dumps(payload, ensure_ascii=False))
                await asyncio.sleep(4.0)
                elapsed += 4.0
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Zalo typing loop stopped for {}: {}", chat_id, e)

    async def send(self, msg: OutboundMessage) -> None:
        """Deliver an outbound response message through the Zalo bridge."""
        self._stop_typing(msg.chat_id)

        if not self._ws or not self._connected:
            raise RuntimeError("Zalo bridge is not connected")

        metadata = msg.metadata or {}
        raw_chat_id = str(msg.chat_id or "")
        is_group = (
            raw_chat_id.startswith("group:")
            or metadata.get("thread_type") == "group"
            or metadata.get("is_group") is True
            or self._chat_thread_types.get(raw_chat_id) == "group"
        )
        thread_type = "group" if is_group else "user"
        target_thread_id = (
            raw_chat_id.removeprefix("group:")
            if raw_chat_id.startswith("group:")
            else raw_chat_id
        )

        quote_id = (
            metadata.get("origin_message_id")
            if self.config.reply_with_quote
            else None
        )
        if not quote_id and self.config.reply_with_quote:
            quote_id = (
                self._last_chat_message_ids.get(target_thread_id)
                or self._last_chat_message_ids.get(raw_chat_id)
            )

        raw_content = msg.content or ""
        chunks = format_and_split_for_zalo(raw_content, max_len=1200)

        for idx, (text, styles) in enumerate(chunks):
            if not text.strip():
                continue
            payload: dict[str, Any] = {
                "type": "send",
                "thread_id": target_thread_id,
                "thread_type": thread_type,
                "text": text,
            }
            if styles:
                payload["styles"] = styles
            if idx == 0 and quote_id:
                payload["quote_id"] = quote_id

            await self._ws.send(json.dumps(payload, ensure_ascii=False))

    def _is_mentioned(
        self,
        mentions: list[dict[str, Any]],
        content: str = "",
        quote: dict[str, Any] | None = None,
    ) -> bool:
        """Check if bot UID is among mentions, quoted in reply, or named in text."""
        bot_uid = str(self.config.bot_user_id or self._bot_user_id or "").strip()
        bot_name = str(self.config.bot_name or self._bot_display_name or "").strip()

        if not bot_uid and not bot_name:
            return False

        # 1. Native Zalo mention in mentions array
        if bot_uid:
            for m in mentions:
                uid = str(m.get("uid") or "")
                # Exclude group-wide mentions (@all has UID "-1" or "0")
                if uid and uid not in ("-1", "0") and uid == bot_uid:
                    return True

        # 2. Quote/reply to a message sent by the bot
        if quote and bot_uid:
            owner_id = str(quote.get("ownerId") or quote.get("uidFrom") or "")
            if owner_id == bot_uid:
                return True

        # 3. Fallback: text mention @BotName in message content
        if bot_name:
            if f"@{bot_name.lower()}" in content.lower():
                return True

        return False

    async def _handle_bridge_message(self, raw: str) -> None:
        """Process incoming JSON event from the bridge."""
        try:
            data = json.loads(raw)
        except Exception:
            logger.warning("Invalid JSON from Zalo bridge: {}", raw[:100])
            return

        msg_type = data.get("type")

        if msg_type == "status":
            status = data.get("status", "")
            if status == "connected":
                self._connected = True
                self._bot_user_id = str(data.get("user_id") or "")
                self._bot_display_name = str(data.get("display_name") or "")
                logger.info(
                    "Zalo bridge authenticated as {} (uid: {})",
                    self._bot_display_name,
                    self._bot_user_id,
                )
            elif status == "duplicate_connection":
                self._connected = False
                self.last_error_status = "duplicate_connection"
                logger.warning(
                    "Zalo Web was opened in another browser/app. Zalo bot listener stopped to prevent session conflict."
                )

        elif msg_type == "message":
            if data.get("is_self"):
                return

            msg_id = data.get("id") or ""
            if msg_id:
                if msg_id in self._processed_message_ids:
                    return
                self._processed_message_ids[msg_id] = None
                while len(self._processed_message_ids) > 1000:
                    self._processed_message_ids.popitem(last=False)

            thread_type = data.get("thread_type", "user")
            thread_id = str(data.get("thread_id") or "")
            sender_id = str(data.get("sender_id") or thread_id)
            content = str(data.get("content") or "")
            raw_mentions = data.get("mentions")
            mentions: list[dict[str, Any]] = (
                [
                    cast(dict[str, Any], m)
                    for m in cast(list[object], raw_mentions)
                    if isinstance(m, dict)
                ]
                if isinstance(raw_mentions, list)
                else []
            )
            raw_quote = data.get("quote")
            quote: dict[str, Any] | None = (
                cast(dict[str, Any], raw_quote) if isinstance(raw_quote, dict) else None
            )

            is_group = (thread_type == "group")
            chat_id = f"group:{thread_id}" if is_group else thread_id

            # Group policy check
            if is_group:
                policy = self.config.group_policy
                if policy == "allowlist":
                    if thread_id not in self.config.group_allow_from:
                        return
                elif policy == "mention":
                    if not self._is_mentioned(mentions, content=content, quote=quote):
                        return

            self._chat_thread_types[thread_id] = thread_type
            self._chat_thread_types[chat_id] = thread_type
            while len(self._chat_thread_types) > 1000:
                self._chat_thread_types.popitem(last=False)

            if msg_id:
                self._last_chat_message_ids[thread_id] = msg_id
                self._last_chat_message_ids[chat_id] = msg_id
                while len(self._last_chat_message_ids) > 1000:
                    self._last_chat_message_ids.popitem(last=False)

            clean_content = content
            bot_name = str(self.config.bot_name or self._bot_display_name or "").strip()
            if bot_name:
                clean_content = re.sub(
                    rf"@{re.escape(bot_name)}\b[:,\s]*", "", clean_content, flags=re.IGNORECASE
                ).strip()

            raw_attachments = data.get("attachments")
            attachments: list[dict[str, Any]] = (
                [
                    cast(dict[str, Any], att)
                    for att in cast(list[object], raw_attachments)
                    if isinstance(att, dict)
                ]
                if isinstance(raw_attachments, list)
                else []
            )
            media_paths: list[str] = []
            if attachments:
                media_paths = await self._download_attachments(attachments)

            if not clean_content and attachments:
                if all(att.get("type") == "image" for att in attachments):
                    clean_content = "Please analyze the attached image(s)."
                else:
                    clean_content = "Please use the attached file(s)."
            elif not clean_content:
                clean_content = content.strip()

            metadata: dict[str, Any] = {
                "origin_message_id": msg_id,
                "thread_type": thread_type,
                "is_group": is_group,
                "sender_name": data.get("sender_name", ""),
                "timestamp": data.get("timestamp"),
            }

            self._start_typing(chat_id, thread_type)

            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=clean_content,
                media=media_paths,
                metadata=metadata,
                is_dm=not is_group,
            )


__all__ = ["ZaloChannel", "ZaloConfig"]
