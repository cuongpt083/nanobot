"""Tests for thread-safe metrics registry."""

from nanobot.pilot.metrics import PilotMetrics


def test_metrics_counters() -> None:
    metrics = PilotMetrics()
    metrics.inc_hook_error()
    metrics.inc_queue_drop("artifact")
    metrics.inc_events_persisted("turn", 2)

    snap = metrics.snapshot()
    assert snap["capture_hook_errors_total"] == 1
    assert snap["queue_drops_by_kind"]["artifact"] == 1
    assert snap["events_persisted_by_kind"]["turn"] == 2
