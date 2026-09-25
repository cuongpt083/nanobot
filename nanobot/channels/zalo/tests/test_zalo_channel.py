"""Tests for Zalo channel runtime and events."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.registry import discover_all, load_channel_class
from nanobot.channels.zalo.runtime import ZaloChannel, ZaloConfig


def test_zalo_config_defaults() -> None:
    config = ZaloConfig()
    assert config.enabled is False
    assert config.bridge_url == "ws://127.0.0.1:3002"
    assert config.bridge_token == ""
    assert config.allow_from == []
    assert config.group_policy == "mention"
    assert config.group_allow_from == []
    assert config.bot_user_id == ""
    assert config.bot_name == ""
    assert config.reply_with_quote is True


def test_zalo_config_custom_values() -> None:
    config = ZaloConfig(
        enabled=True,
        bridge_url="ws://10.0.0.5:8080",
        bridge_token="secret-123",
        allow_from=["uid_user_1", "uid_user_2"],
        group_policy="open",
        bot_user_id="bot-custom-id",
        bot_name="NanobotAssistant",
        reply_with_quote=False,
    )
    assert config.enabled is True
    assert config.bridge_url == "ws://10.0.0.5:8080"
    assert config.bridge_token == "secret-123"
    assert config.allow_from == ["uid_user_1", "uid_user_2"]
    assert config.group_policy == "open"
    assert config.bot_user_id == "bot-custom-id"
    assert config.bot_name == "NanobotAssistant"
    assert config.reply_with_quote is False


def test_zalo_channel_discovery() -> None:
    cls = load_channel_class("zalo")
    assert cls is ZaloChannel
    assert cls.name == "zalo"
    assert cls.display_name == "Zalo"
    assert "zalo" in discover_all()


@pytest.fixture
def mock_bus() -> MagicMock:
    bus = MagicMock(spec=MessageBus)
    bus.publish_inbound = AsyncMock()
    return bus


@pytest.mark.asyncio
async def test_zalo_inbound_dm_message(mock_bus: MagicMock) -> None:
    config = ZaloConfig(enabled=True, allow_from=["*"])
    channel = ZaloChannel(config, mock_bus)

    payload = {
        "type": "message",
        "id": "msg-001",
        "thread_id": "user-123",
        "thread_type": "user",
        "sender_id": "user-123",
        "sender_name": "Alice",
        "content": "Hello nanobot",
        "is_self": False,
        "mentions": [],
        "quote": None,
        "timestamp": 1725390000000,
    }

    await channel._handle_bridge_message(json.dumps(payload))

    mock_bus.publish_inbound.assert_called_once()
    inbound: InboundMessage = mock_bus.publish_inbound.call_args[0][0]
    assert inbound.channel == "zalo"
    assert inbound.chat_id == "user-123"
    assert inbound.sender_id == "user-123"
    assert inbound.content == "Hello nanobot"
    assert inbound.metadata["origin_message_id"] == "msg-001"
    assert inbound.metadata["thread_type"] == "user"


@pytest.mark.asyncio
async def test_zalo_inbound_ignores_self_message(mock_bus: MagicMock) -> None:
    config = ZaloConfig(enabled=True, allow_from=["*"])
    channel = ZaloChannel(config, mock_bus)

    payload = {
        "type": "message",
        "id": "msg-002",
        "thread_id": "user-123",
        "thread_type": "user",
        "sender_id": "bot-self",
        "sender_name": "Bot",
        "content": "I am the bot",
        "is_self": True,
    }

    await channel._handle_bridge_message(json.dumps(payload))
    mock_bus.publish_inbound.assert_not_called()


@pytest.mark.asyncio
async def test_zalo_inbound_group_mention_policy(mock_bus: MagicMock) -> None:
    config = ZaloConfig(enabled=True, allow_from=["*"], group_policy="mention")
    channel = ZaloChannel(config, mock_bus)

    # 1. When _bot_user_id is not yet known, group messages MUST be ignored
    no_bot_id_msg = {
        "type": "message",
        "id": "msg-002b",
        "thread_id": "group-456",
        "thread_type": "group",
        "sender_id": "user-123",
        "content": "Hello everyone",
        "is_self": False,
        "mentions": [],
    }
    await channel._handle_bridge_message(json.dumps(no_bot_id_msg))
    mock_bus.publish_inbound.assert_not_called()

    # Set bot user ID
    channel._bot_user_id = "bot-999"

    # 2. Message without mention -> ignored
    no_mention = {
        "type": "message",
        "id": "msg-003",
        "thread_id": "group-456",
        "thread_type": "group",
        "sender_id": "user-123",
        "content": "General chatter",
        "is_self": False,
        "mentions": [{"uid": "other-user", "pos": 0, "len": 5}],
    }
    await channel._handle_bridge_message(json.dumps(no_mention))
    mock_bus.publish_inbound.assert_not_called()

    # 3. Message with @all (uid: "-1" or "0") -> ignored
    all_mention = {
        "type": "message",
        "id": "msg-003b",
        "thread_id": "group-456",
        "thread_type": "group",
        "sender_id": "user-123",
        "content": "@all Meeting at 3pm",
        "is_self": False,
        "mentions": [{"uid": "-1", "pos": 0, "len": 4}],
    }
    await channel._handle_bridge_message(json.dumps(all_mention))
    mock_bus.publish_inbound.assert_not_called()

    # 4. Message with bot mention -> accepted
    with_mention = {
        "type": "message",
        "id": "msg-004",
        "thread_id": "group-456",
        "thread_type": "group",
        "sender_id": "user-123",
        "content": "@Bot What is 2+2?",
        "is_self": False,
        "mentions": [{"uid": "bot-999", "pos": 0, "len": 4}],
    }
    await channel._handle_bridge_message(json.dumps(with_mention))
    mock_bus.publish_inbound.assert_called_once()
    inbound = mock_bus.publish_inbound.call_args[0][0]
    assert inbound.chat_id == "group:group-456"
    assert inbound.metadata["thread_type"] == "group"
    assert inbound.metadata["is_group"] is True

    mock_bus.publish_inbound.reset_mock()

    # 5. Message replying (quoting) a message sent by the bot -> accepted
    quote_reply = {
        "type": "message",
        "id": "msg-004b",
        "thread_id": "group-456",
        "thread_type": "group",
        "sender_id": "user-123",
        "content": "Explain more please",
        "is_self": False,
        "mentions": [],
        "quote": {"ownerId": "bot-999", "msg": "Previous answer"},
    }
    await channel._handle_bridge_message(json.dumps(quote_reply))
    mock_bus.publish_inbound.assert_called_once()

    mock_bus.publish_inbound.reset_mock()

    # 6. Text mention @BotName with configured bot_name -> accepted
    channel.config.bot_name = "Nanobot"
    text_mention = {
        "type": "message",
        "id": "msg-004c",
        "thread_id": "group-456",
        "thread_type": "group",
        "sender_id": "user-123",
        "content": "@Nanobot help me write python code",
        "is_self": False,
        "mentions": [],
    }
    await channel._handle_bridge_message(json.dumps(text_mention))
    mock_bus.publish_inbound.assert_called_once()


@pytest.mark.asyncio
async def test_zalo_inbound_allow_from_filter(mock_bus: MagicMock) -> None:
    config = ZaloConfig(enabled=True, allow_from=["allowed-user"])
    channel = ZaloChannel(config, mock_bus)
    channel._connected = True
    mock_ws = MagicMock()
    mock_ws.send = AsyncMock()
    channel._ws = mock_ws

    blocked = {
        "type": "message",
        "id": "msg-005",
        "thread_id": "unauthorized-user",
        "thread_type": "user",
        "sender_id": "unauthorized-user",
        "content": "Secret request",
        "is_self": False,
    }
    await channel._handle_bridge_message(json.dumps(blocked))
    # BaseChannel sends pairing code for unapproved DM, doesn't publish inbound to bus
    mock_bus.publish_inbound.assert_not_called()
    mock_ws.send.assert_called_once()
    payload = json.loads(mock_ws.send.call_args[0][0])
    assert "pairing code" in payload["text"].lower()


@pytest.mark.asyncio
async def test_zalo_outbound_send(mock_bus: MagicMock) -> None:
    config = ZaloConfig(enabled=True, allow_from=["*"], reply_with_quote=True)
    channel = ZaloChannel(config, mock_bus)
    channel._connected = True

    mock_ws = MagicMock()
    mock_ws.send = AsyncMock()
    channel._ws = mock_ws

    msg = OutboundMessage(
        channel="zalo",
        chat_id="user-456",
        content="# Chào bạn\nĐây là câu trả lời với **chữ đậm**.",
        metadata={"origin_message_id": "quote-999"},
    )

    await channel.send(msg)

    mock_ws.send.assert_called_once()
    payload = json.loads(mock_ws.send.call_args[0][0])
    assert payload["type"] == "send"
    assert payload["thread_id"] == "user-456"
    assert payload["thread_type"] == "user"
    assert "📌 Chào bạn" in payload["text"]
    assert "chữ đậm" in payload["text"]
    assert "**" not in payload["text"]
    assert payload["quote_id"] == "quote-999"
    assert isinstance(payload["styles"], list)
    assert len(payload["styles"]) >= 2
