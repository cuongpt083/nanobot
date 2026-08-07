"""Tests for privacy and consent slash commands."""

from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_consent, cmd_privacy
from nanobot.command.router import CommandContext
from nanobot.pilot.service import PilotService


@pytest.mark.asyncio
async def test_consent_commands(tmp_path) -> None:
    service = PilotService(db_path=tmp_path / "pilot_cmd.db", hmac_secret="secret")
    await service.start()

    loop_mock = MagicMock()
    loop_mock.pilot_service = service

    inbound = InboundMessage(
        channel="webui",
        sender_id="usr_123",
        chat_id="chat_1",
        content="/consent status",
    )

    ctx = CommandContext(
        msg=inbound,
        session=None,
        key="key",
        raw="/consent status",
        args="status",
        loop=loop_mock,
    )

    # Initial status check
    reply = await cmd_consent(ctx)
    assert reply is not None
    assert "Product capture: OFF" in reply.content

    # Toggle product consent ON
    ctx.args = "product on"
    reply_on = await cmd_consent(ctx)
    assert reply_on is not None
    assert "Product capture updated to: ON" in reply_on.content

    # Check status again
    ctx.args = "status"
    reply_status = await cmd_consent(ctx)
    assert reply_status is not None
    assert "Product capture: ON" in reply_status.content

    await service.stop()


@pytest.mark.asyncio
async def test_privacy_delete_command(tmp_path) -> None:
    service = PilotService(db_path=tmp_path / "pilot_del.db", hmac_secret="secret")
    await service.start()

    loop_mock = MagicMock()
    loop_mock.pilot_service = service

    inbound = InboundMessage(
        channel="webui",
        sender_id="usr_del",
        chat_id="chat_del",
        content="/privacy delete",
    )

    ctx = CommandContext(
        msg=inbound,
        session=None,
        key="key",
        raw="/privacy delete",
        args="delete",
        loop=loop_mock,
    )

    reply = await cmd_privacy(ctx)
    assert reply is not None
    assert "Privacy deletion completed" in reply.content

    await service.stop()
