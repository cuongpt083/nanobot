"""Tests for the durable coworker cache/keep-warm/optimize metrics store."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from nanobot.coworker.metrics_store.models import MetricRow
from nanobot.coworker.metrics_store.store import (
    MAX_DAYS_RETAINED,
    SCHEMA_VERSION,
    CoworkerMetricsStore,
)


def _at(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def _store(tmp_path: Path) -> CoworkerMetricsStore:
    store = CoworkerMetricsStore(tmp_path / "coworker_metrics.sqlite3")
    # Keep fixed test dates alive: skip the real-clock age prune (write count stays well under the cap).
    store._last_prune_utc_day = int(time.time() // 86_400)
    return store


def _turn(at: str, *, source: str = "user", **kw: object) -> MetricRow:
    return MetricRow(at_ms=_at(at), kind="turn", source=source, provider="anthropic", model="claude", **kw)


def _ping(at: str, **kw: object) -> MetricRow:
    return MetricRow(at_ms=_at(at), kind="ping", source="system", provider="anthropic", model="claude", **kw)


def test_schema_is_content_free_with_version_and_wal(tmp_path: Path) -> None:
    path = tmp_path / "coworker_metrics.sqlite3"
    store = CoworkerMetricsStore(path)
    store.record(_turn("2026-06-03T00:00:00+00:00", input_tokens=100, output_tokens=20))

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(coworker_metrics)")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert version == SCHEMA_VERSION
    assert str(mode).lower() == "wal"
    assert "session_key" not in columns
    assert not {"messages", "prompt", "content", "response", "tool_calls"} & columns


def test_payload_aggregates_days_sources_and_keepalive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(
        _turn(
            "2026-06-02T23:30:00+00:00",
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=40,
            cache_write_tokens=10,
            observed_input_tokens=100,
            warm=True,
            original_messages=10,
            sent_messages=7,
        )
    )
    store.record(_turn("2026-06-03T01:00:00+00:00", source="api", input_tokens=50, output_tokens=5))
    store.record(
        _ping(
            "2026-06-03T01:05:00+00:00",
            input_tokens=90,
            output_tokens=1,
            cache_read_tokens=88,
            warm_hit=True,
        )
    )
    store.record(_ping("2026-06-03T01:10:00+00:00", failure=True))

    payload = store.metrics_payload(
        timezone_name="UTC",
        now=datetime(2026, 6, 3, 12, tzinfo=timezone.utc),
    )

    assert payload["total_turns_30d"] == 2
    assert payload["total_pings_30d"] == 2
    assert payload["warm_turns_30d"] == 1
    assert payload["warm_hits_30d"] == 1
    assert payload["ping_failures_30d"] == 1
    assert payload["cache_read_tokens_30d"] == 40
    assert payload["cache_write_tokens_30d"] == 10
    assert payload["observed_input_tokens_30d"] == 100
    assert payload["cache_read_rate_30d"] == 0.4
    assert payload["saved_messages_30d"] == 3
    assert payload["ping_cache_read_tokens_30d"] == 88

    days = {row["date"]: row for row in payload["days"]}
    assert days["2026-06-02"]["cache_read_rate"] == 0.4
    assert days["2026-06-03"]["turns"] == 1
    assert days["2026-06-03"]["pings"] == 2
    assert days["2026-06-03"]["saved_messages"] == 0

    sources = {row["source"]: row for row in payload["sources_30d"]}
    assert sources["user"]["cache_read_tokens"] == 40
    assert sources["user"]["cache_read_rate"] == 0.4
    assert sources["api"]["cache_read_rate"] is None


def test_payload_cache_is_isolated_and_invalidated_on_write(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record(_turn("2026-06-03T00:00:00+00:00", input_tokens=10, output_tokens=2))
    kwargs = {"now": datetime(2026, 6, 3, 12, tzinfo=timezone.utc)}

    first = store.metrics_payload(**kwargs)
    first["days"].clear()
    cached = store.metrics_payload(**kwargs)
    assert cached["total_turns_30d"] == 1
    assert cached["days"]

    store.record(_turn("2026-06-03T00:01:00+00:00", input_tokens=10, output_tokens=2))
    assert store.metrics_payload(**kwargs)["total_turns_30d"] == 2


def test_payload_cache_is_invalidated_when_connection_pid_changes(tmp_path: Path) -> None:
    path = tmp_path / "coworker_metrics.sqlite3"
    store = CoworkerMetricsStore(path)
    store._last_prune_utc_day = int(time.time() // 86_400)
    other = CoworkerMetricsStore(path)
    other._last_prune_utc_day = store._last_prune_utc_day
    kwargs = {"now": datetime(2026, 6, 3, 12, tzinfo=timezone.utc)}

    store.record(_turn("2026-06-03T00:00:00+00:00", input_tokens=1))
    assert store.metrics_payload(**kwargs)["total_turns_30d"] == 1

    other.record(_turn("2026-06-03T00:01:00+00:00", input_tokens=1))
    store._connection_pid = -1

    assert store.metrics_payload(**kwargs)["total_turns_30d"] == 2
    other.close()


def test_age_pruning_drops_rows_beyond_retention(tmp_path: Path) -> None:
    store = CoworkerMetricsStore(tmp_path / "coworker_metrics.sqlite3")
    old_ms = int(
        (datetime.now(timezone.utc).timestamp() - (MAX_DAYS_RETAINED + 5) * 86_400) * 1000
    )
    store.record(MetricRow(at_ms=old_ms, kind="turn", source="user"))
    assert store.count() == 0
