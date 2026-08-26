from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.zalo.client import ZaloBridgeError
from nanobot.channels.zalo.messages import (
    THREAD_TYPE_GROUP,
    THREAD_TYPE_USER,
    group_message_is_addressed,
    normalize_inbound_message,
)
from nanobot.channels.zalo.runtime import ZaloChannel
from nanobot.channels.zalo.state import local_state_present
from nanobot.channels.zalo.validation import validate


def _inbound(
    *,
    thread_type: int = THREAD_TYPE_USER,
    uid_from: str = "111",
    id_to: str = "222",
    content: str | dict[str, Any] = "hello",
    is_self: bool = False,
    mentions: list[dict[str, Any]] | None = None,
    quote_owner: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "msgId": "m1",
        "uidFrom": uid_from,
        "idTo": id_to,
        "content": content,
        "dName": "Alice",
        "ts": 1_700_000_000,
    }
    if mentions is not None:
        data["mentions"] = mentions
    if quote_owner is not None:
        data["quote"] = {"ownerId": quote_owner, "msg": "prior"}
    return {"type": thread_type, "isSelf": is_self, "data": data}


def test_normalize_skips_self_and_missing_ids() -> None:
    assert normalize_inbound_message(_inbound(is_self=True)) is None
    assert normalize_inbound_message(_inbound(uid_from="", id_to="")) is None


def test_normalize_direct_message_and_media() -> None:
    inbound = normalize_inbound_message(
        _inbound(content={"title": "Photo", "href": "https://cdn.example/a.jpg"}),
        own_user_id="999",
    )
    assert inbound is not None
    assert inbound.thread_id == "111"
    assert inbound.sender_id == "111"
    assert inbound.is_group is False
    assert "Photo" in inbound.content
    assert inbound.media == ("https://cdn.example/a.jpg",)


def test_normalize_group_mentions_and_quote() -> None:
    mentioned = normalize_inbound_message(
        _inbound(
            thread_type=THREAD_TYPE_GROUP,
            uid_from="111",
            id_to="555",
            mentions=[{"uid": "999"}],
        ),
        own_user_id="999",
    )
    assert mentioned is not None
    assert mentioned.is_group is True
    assert mentioned.thread_id == "555"
    assert mentioned.mentioned is True

    quoted = normalize_inbound_message(
        _inbound(thread_type=THREAD_TYPE_GROUP, uid_from="111", id_to="555", quote_owner="999"),
        own_user_id="999",
    )
    assert quoted is not None
    assert quoted.mentioned is True


def test_group_message_is_addressed_by_name() -> None:
    inbound = normalize_inbound_message(
        _inbound(thread_type=THREAD_TYPE_GROUP, uid_from="111", id_to="555", content="@Bot help"),
        own_user_id="999",
    )
    assert inbound is not None
    assert group_message_is_addressed(inbound, "Bot") is True
    assert group_message_is_addressed(inbound, "Other") is False


def test_local_state_present(tmp_path) -> None:
    creds = tmp_path / "credentials.json"
    creds.write_text(json.dumps({"imei": "i", "cookie": [{"name": "zpw"}], "userAgent": "ua"}))
    assert local_state_present({"stateDir": str(tmp_path)}) is True
    assert local_state_present({"stateDir": str(tmp_path / "missing")}) is False


def test_validate_needs_setup_until_enabled() -> None:
    result = validate({}, ChannelValidationContext())
    assert result["status"] == "needs_setup"
    configured = validate({"enabled": True}, ChannelValidationContext())
    assert configured["status"] == "configured"


def _make_channel(config: dict[str, Any] | None = None) -> ZaloChannel:
    merged = {"enabled": True, "allowFrom": ["*"]}
    if config:
        merged.update(config)
    return ZaloChannel(merged, MagicMock())


class _FakeBridge:
    def __init__(self) -> None:
        self.running = True
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.call = AsyncMock(side_effect=self._call)
        self.start = AsyncMock()
        self.stop = AsyncMock()

    async def _call(self, method: str, params: dict[str, Any] | None = None, **_kwargs: Any) -> dict[str, Any]:
        self.calls.append((method, params or {}))
        if method == "send":
            return {"messageId": "out-1"}
        if method == "typing":
            return {"ok": True}
        if method == "login_session":
            return {"authenticated": True, "userId": "999"}
        return {}


@pytest.mark.asyncio
async def test_send_chunks_and_attachments(tmp_path) -> None:
    image = tmp_path / "photo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    channel = _make_channel()
    bridge = _FakeBridge()
    channel._bridge = bridge  # type: ignore[assignment]
    await channel.send(
        OutboundMessage(
            channel="zalo",
            chat_id="111",
            content="a" * 2500,
            media=[str(image)],
            metadata={"is_group": False},
        )
    )
    send_calls = [params for method, params in bridge.calls if method == "send"]
    assert len(send_calls) == 2
    assert send_calls[0]["attachments"] == [{"path": str(image)}]
    assert "attachments" not in send_calls[1]


@pytest.mark.asyncio
async def test_handle_inbound_publishes_allowed_dm() -> None:
    bus = MessageBus()
    channel = ZaloChannel({"enabled": True, "allowFrom": ["*"]}, bus)
    inbound = _inbound(uid_from="111", content="hi")
    await channel._handle_inbound(inbound)
    msg = await bus.consume_inbound()
    assert msg.channel == "zalo"
    assert msg.sender_id == "111"
    assert msg.content == "hi"


@pytest.mark.asyncio
async def test_group_mention_policy_drops_unmentioned() -> None:
    bus = MessageBus()
    channel = ZaloChannel(
        {"enabled": True, "allowFrom": ["*"], "groupPolicy": "mention"},
        bus,
    )
    channel._own_user_id = "999"
    await channel._handle_inbound(
        _inbound(thread_type=THREAD_TYPE_GROUP, uid_from="111", id_to="555", content="hello")
    )
    assert bus.inbound_size == 0


@pytest.mark.asyncio
async def test_start_error_message_exposes_bridge_errors() -> None:
    channel = _make_channel()
    assert channel.start_error_message(ZaloBridgeError("need node")) == "need node"
    assert channel.start_error_message(RuntimeError("x")) is None


def test_default_config() -> None:
    config = ZaloChannel.default_config()
    assert config["enabled"] is False
    assert config["groupPolicy"] == "mention"
    assert config["allowFrom"] == []


def test_thread_id_strips_group_prefix() -> None:
    assert ZaloChannel._thread_id("group:555") == "555"
    assert ZaloChannel._chat_is_group("group:555", None) is True
    assert ZaloChannel._chat_is_group("111", {"is_group": True}) is True
    assert ZaloChannel._chat_is_group("111", None) is False
