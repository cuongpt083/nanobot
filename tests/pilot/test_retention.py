"""Tests for RetentionService planning and execution."""

import time

from nanobot.pilot.retention import RetentionService
from nanobot.pilot.store import SQLitePilotStore


def test_retention_plan(tmp_path) -> None:
    store = SQLitePilotStore(tmp_path / "retention.db")
    service = RetentionService(store=store, retention_days=90)

    now_ms = int(time.time() * 1000)
    plan = service.plan(now_ms=now_ms)

    assert plan["now_ms"] == now_ms
    assert plan["retention_days"] == 90
    assert plan["eligible_old_turns"] == 0

    apply_result = service.apply(plan)
    assert apply_result["pruned_turns"] == 0
    store.close()
