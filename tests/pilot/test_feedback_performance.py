"""Performance benchmark tests: feedback acknowledgement P95 <= 1 s."""

import time

import pytest

from nanobot.bus.events import FeedbackAction
from nanobot.pilot.feedback import FeedbackService
from nanobot.pilot.identity import IdentityHasher
from nanobot.pilot.store import SQLitePilotStore
from nanobot.pilot.types import CapturePriority, QueueEvent


@pytest.mark.asyncio
async def test_feedback_handling_performance(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "fb_perf.db")
    hasher = IdentityHasher("secret")
    service = FeedbackService(store=store, hasher=hasher)

    user_pseudo = hasher.hash_identity("user", "webui:user_perf")
    store.write_batch(
        [
            QueueEvent(
                event_id="t_perf",
                priority=CapturePriority.FINAL,
                kind="turn",
                payload={
                    "turn_id": "turn_perf_fb",
                    "user_pseudonym": user_pseudo,
                    "session_pseudonym": "sess_perf",
                    "channel": "webui",
                    "chat_id": "user_perf",
                },
                created_at_ms=1000,
            )
        ]
    )

    latencies: list[float] = []

    for i in range(30):
        action = FeedbackAction(
            action_id=f"act_perf_{i}",
            turn_id="turn_perf_fb",
            kind="helpful",
            channel="webui",
            sender_id="user_perf",
            chat_id="user_perf",
            session_key="webui:user_perf",
        )

        start = time.perf_counter()
        ack = await service.handle_action(action)
        elapsed_ms = (time.perf_counter() - start) * 1000
        latencies.append(elapsed_ms)
        assert ack.accepted is True

    latencies.sort()
    p95_ms = latencies[int(len(latencies) * 0.95)]
    assert p95_ms <= 1000.0, f"Feedback ack P95 latency {p95_ms:.2f} ms exceeded 1000 ms target"

    store.close()
