"""Durable coding-run records in the coworker metrics store."""

from __future__ import annotations

import time
from pathlib import Path

from nanobot.coworker import metrics_store
from nanobot.coworker.metrics_store.models import CodingRunRow


def test_record_and_query_coding_runs(tmp_path: Path) -> None:
    store = metrics_store.get_metrics_store(path=tmp_path / "metrics.sqlite3")
    store.record_coding_run(CodingRunRow(
        at_ms=int(time.time() * 1000),
        task_id="ct-1",
        backend="pi",
        mode="worktree",
        status="succeeded",
        fix_rounds=1,
        settle_continuations=2,
        blocked_calls=3,
        questions=1,
        total_tokens=1170,
        cost=0.0025,
        duration_ms=5000,
        phase_stats_json='{"plan": {"tokens": 100, "cost": 0.001, "seconds": 1.0}}',
    ))

    runs = store.coding_runs()
    assert len(runs) == 1
    run = runs[0]
    assert run["task_id"] == "ct-1"
    assert run["status"] == "succeeded"
    assert run["fix_rounds"] == 1
    assert run["settle_continuations"] == 2
    assert run["blocked_calls"] == 3
    assert run["total_tokens"] == 1170
    assert run["phase_stats"]["plan"]["tokens"] == 100


def test_record_coding_run_fail_open(tmp_path: Path) -> None:
    # The fail-open wrapper must never raise even for a bad store path.
    metrics_store.record_coding_run(
        task_id="ct-x",
        status="succeeded",
        phase_stats={"plan": {"tokens": 1}},
    )
