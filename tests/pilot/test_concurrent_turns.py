"""Concurrency regression tests: 20 active turns across WebUI and Telegram."""

import asyncio

import pytest

from nanobot.agent.hook import AgentRunHookContext, AgentTurnHookContext
from nanobot.pilot.service import PilotService


@pytest.mark.asyncio
async def test_20_concurrent_turns(tmp_path) -> None:
    db_file = tmp_path / "concurrent.db"
    service = PilotService(db_path=db_file, hmac_secret="concurrent_secret")
    await service.start()

    async def run_simulated_turn(idx: int) -> tuple[str, str]:
        channel = "webui" if idx % 2 == 0 else "telegram"
        sender_id = f"user_{idx}"
        turn_id = f"turn_id_{idx}"

        turn_ctx = AgentTurnHookContext(
            channel=channel,
            chat_id=sender_id,
            turn_id=turn_id,
            provider_config={"capture_policy": "answer"},
        )
        hook = service.hook_factory(turn_ctx)

        run_ctx = AgentRunHookContext(
            messages=[{"role": "user", "content": f"User query {idx}"}],
            final_content=f"Assistant answer {idx}",
        )
        await hook.after_run(run_ctx)

        user_pseudo = service.hasher.hash_identity("user", f"{channel}:{sender_id}")
        return turn_id, user_pseudo

    tasks = [asyncio.create_task(run_simulated_turn(i)) for i in range(20)]
    results = await asyncio.gather(*tasks)

    # Verify 20 unique turn IDs returned
    turn_ids = {r[0] for r in results}
    assert len(turn_ids) == 20

    # Allow background writer loop to flush
    await asyncio.sleep(0.1)

    health = await service.health_snapshot()
    assert health["accepted_total"] >= 20

    await service.stop()
