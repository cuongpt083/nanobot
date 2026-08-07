"""Tests for PilotService lifecycle and background worker persistence."""

import asyncio

import pytest

from nanobot.agent.hook import AgentRunHookContext, AgentTurnHookContext
from nanobot.pilot.service import PilotService


@pytest.mark.asyncio
async def test_pilot_service_lifecycle(tmp_path) -> None:
    db_file = tmp_path / "pilot_test.db"
    service = PilotService(db_path=db_file, hmac_secret="test_secret")

    await service.start()

    turn_ctx = AgentTurnHookContext(
        channel="webui",
        chat_id="user_test",
        turn_id="t_srv_1",
    )
    hook = service.hook_factory(turn_ctx)

    run_ctx = AgentRunHookContext(
        messages=[{"role": "user", "content": "Test message"}],
        final_content="Test response",
    )

    await hook.after_run(run_ctx)

    # Allow worker loop to consume queue item
    await asyncio.sleep(0.1)

    health = await service.health_snapshot()
    assert health["status"] == "ok"
    assert health["accepted_total"] >= 1

    await service.stop()
    health_stopped = await service.health_snapshot()
    assert health_stopped["status"] == "stopped"
