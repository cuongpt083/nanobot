"""Zalo-owned interactive QR connection flow."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from nanobot.channels.connect import ChannelConnectError, QueryParams, query_first
from nanobot.channels.zalo.state import local_state_present
from nanobot.config.loader import load_config

if TYPE_CHECKING:
    from nanobot.channels.zalo.runtime import ZaloChannel


@dataclass(slots=True)
class ZaloConnectSession:
    id: str
    qr_url: str
    channel: ZaloChannel
    force: bool
    created_wall: float
    deadline: float


class ZaloConnectStore:
    """In-memory Zalo QR login sessions for the WebUI."""

    def __init__(self) -> None:
        self._sessions: dict[str, ZaloConnectSession] = {}

    async def handle(self, action: str, query: QueryParams) -> dict[str, Any]:
        if action == "start":
            force = (query_first(query, "force") or "").strip().lower() in {
                "1",
                "true",
                "yes",
            }
            return await self.start(force=force)

        session_id = (query_first(query, "session_id") or "").strip()
        if not session_id:
            raise ChannelConnectError("missing Zalo connect session")
        if action == "poll":
            return await self.poll(session_id)
        if action == "cancel":
            return await self.cancel(session_id)
        raise ChannelConnectError(f"unsupported Zalo connect action: {action}", status=404)

    async def start(self, *, force: bool = False) -> dict[str, Any]:
        await self._cleanup()
        channel = self._build_channel()
        if not force and local_state_present(channel.config):
            return {
                "session_id": "",
                "status": "succeeded",
                "message": "Zalo is already connected.",
                "interval_ms": 2000,
            }
        try:
            qr_url = await channel.connect_start_qr(force=force)
        except Exception as exc:
            await self._close_channel(channel)
            raise ChannelConnectError(
                f"Unable to start Zalo QR login: {exc}",
                status=502,
            ) from exc
        if not qr_url:
            await self._close_channel(channel)
            return {
                "session_id": "",
                "status": "succeeded",
                "message": "Zalo is already connected.",
                "interval_ms": 2000,
            }
        session_id = secrets.token_urlsafe(18)
        now_wall = time.time()
        self._sessions[session_id] = ZaloConnectSession(
            id=session_id,
            qr_url=qr_url,
            channel=channel,
            force=force,
            created_wall=now_wall,
            deadline=time.monotonic() + 600,
        )
        return self._pending_payload(self._sessions[session_id])

    async def poll(self, session_id: str) -> dict[str, Any]:
        await self._cleanup()
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "session_id": session_id,
                "status": "expired",
                "message": "This Zalo login has expired. Start again.",
            }
        try:
            status = await session.channel.connect_poll_qr()
        except Exception as exc:
            self._sessions.pop(session_id, None)
            await self._close_channel(session.channel)
            return {
                "session_id": session_id,
                "status": "failed",
                "message": f"Zalo QR login failed: {exc}",
            }
        state = str(status.get("status") or "pending")
        if state == "succeeded":
            self._sessions.pop(session_id, None)
            await self._close_channel(session.channel)
            return {
                "session_id": session_id,
                "status": "succeeded",
                "message": str(status.get("message") or "Zalo is connected."),
                "account": str(status.get("account") or ""),
            }
        if state == "failed":
            self._sessions.pop(session_id, None)
            await self._close_channel(session.channel)
            return {
                "session_id": session_id,
                "status": "failed",
                "message": str(status.get("message") or "Zalo QR login failed."),
            }
        qr_url = str(status.get("qr_url") or session.qr_url)
        if qr_url:
            session.qr_url = qr_url
        return self._pending_payload(session)

    async def cancel(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await self._close_channel(session.channel)
        return {
            "session_id": session_id,
            "status": "cancelled",
            "message": "Zalo login cancelled.",
        }

    async def _cleanup(self) -> None:
        now = time.monotonic()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now >= session.deadline
        ]
        for session_id in expired:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                await self._close_channel(session.channel)

    @staticmethod
    def _build_channel() -> ZaloChannel:
        from nanobot.bus.queue import MessageBus
        from nanobot.channels.zalo.runtime import ZaloChannel

        section = getattr(load_config().channels, "zalo", None)
        if section is not None and hasattr(section, "model_dump"):
            config = section.model_dump(mode="json", by_alias=True)
        elif isinstance(section, dict):
            config = dict(cast(dict[str, Any], section))
        else:
            config = {}
        return ZaloChannel(config, MessageBus())

    @staticmethod
    async def _close_channel(channel: ZaloChannel) -> None:
        await channel.connect_close()

    @staticmethod
    def _pending_payload(session: ZaloConnectSession) -> dict[str, Any]:
        return {
            "session_id": session.id,
            "status": "pending",
            "qr_url": session.qr_url,
            "interval_ms": 2000,
            "expires_at_ms": int((session.created_wall + 600) * 1000),
            "message": "Scan with the Zalo app to connect.",
        }


__all__ = ["ZaloConnectStore"]
