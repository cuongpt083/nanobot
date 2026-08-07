"""Performance benchmark tests: capture hook enqueue latency <= 50 ms P95."""

import time

import pytest

from nanobot.agent.hook import AgentRunHookContext, AgentTurnHookContext
from nanobot.pilot.service import PilotService


@pytest.mark.asyncio
async def test_capture_hook_enqueue_performance(tmp_path) -> None:
    db_file = tmp_path / "perf.db"
    service = PilotService(db_path=db_file, hmac_secret="perf_secret")
    await service.start()

    latencies: list[float] = []

    for i in range(50):
        turn_ctx = AgentTurnHookContext(
            channel="webui",
            chat_id=f"user_{i}",
            turn_id=f"turn_perf_{i}",
            provider_config={"capture_policy": "answer"},
        )
        hook = service.hook_factory(turn_ctx)
        run_ctx = AgentRunHookContext(
            messages=[{"role": "user", "content": "Benchmark input"}],
            final_content="Benchmark answer",
        )

        start = time.perf_counter()
        await hook.after_run(run_ctx)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)

    latencies.sort()
    # P95 is at 95th percentile index (~47 of 50)
    p95_ms = latencies[int(len(latencies) * 0.95)]

    assert p95_ms <= 50.0, f"Capture hook enqueue P95 latency {p95_ms:.2f} ms exceeded 50 ms target"

    await service.stop()
