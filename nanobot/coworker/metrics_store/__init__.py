"""Durable 30-day history for the coworker cache / keep-warm / optimize layers.

Content-free and fail-open, mirroring :mod:`nanobot.llm_usage`: writing a metric
never raises into the agent loop, and reading falls back to an empty payload.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.coworker.metrics_store.models import CodingRunRow, MetricKind, MetricRow
from nanobot.coworker.metrics_store.store import CoworkerMetricsStore
from nanobot.llm_usage.context import source_from_session_key

_STORES_LOCK = threading.Lock()
_STORES: dict[Path, CoworkerMetricsStore] = {}


def empty_metrics_payload() -> dict[str, Any]:
    return {
        "days": [],
        "total_turns_30d": 0,
        "total_pings_30d": 0,
        "input_tokens_30d": 0,
        "output_tokens_30d": 0,
        "cache_read_tokens_30d": 0,
        "cache_write_tokens_30d": 0,
        "observed_input_tokens_30d": 0,
        "cache_read_rate_30d": None,
        "ping_input_tokens_30d": 0,
        "ping_output_tokens_30d": 0,
        "ping_cache_read_tokens_30d": 0,
        "ping_cache_write_tokens_30d": 0,
        "warm_turns_30d": 0,
        "warm_hits_30d": 0,
        "ping_failures_30d": 0,
        "original_messages_30d": 0,
        "sent_messages_30d": 0,
        "saved_messages_30d": 0,
        "trimmed_messages_30d": 0,
        "dropped_messages_30d": 0,
        "rewritten_messages_30d": 0,
        "system_holds_30d": 0,
        "sources_30d": [],
        "updated_at": None,
    }


def metrics_store_path() -> Path:
    return get_data_dir() / "coworker_metrics.sqlite3"


def get_metrics_store(path: Path | None = None) -> CoworkerMetricsStore:
    resolved = (path or metrics_store_path()).resolve(strict=False)
    with _STORES_LOCK:
        store = _STORES.get(resolved)
        if store is None:
            store = CoworkerMetricsStore(resolved)
            _STORES[resolved] = store
        return store


def _int_attr(obj: Any, name: str) -> int:
    value = getattr(obj, name, None)
    return int(value) if isinstance(value, int) and value > 0 else 0


def _reported_cache(usage: Any) -> bool:
    return (
        getattr(usage, "cache_read_tokens", None) is not None
        or getattr(usage, "cache_write_tokens", None) is not None
    )


def _int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) and value > 0 else 0


def record_turn(
    *,
    session_key: str | None,
    provider: str,
    model: str,
    usage: Any,
    optimize: dict[str, Any] | None = None,
    warm: bool = False,
    source: str | None = None,
    now: float | None = None,
) -> None:
    """Persist one agent iteration; fail-open (never raises into the loop)."""
    try:
        if usage is None:
            return
        input_tokens = _int_attr(usage, "input_tokens")
        if input_tokens <= 0:
            return
        opt = optimize or {}
        row = MetricRow(
            at_ms=int((now if now is not None else time.time()) * 1000),
            kind="turn",
            source=source or source_from_session_key(session_key),
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=_int_attr(usage, "output_tokens"),
            cache_read_tokens=_int_attr(usage, "cache_read_tokens"),
            cache_write_tokens=_int_attr(usage, "cache_write_tokens"),
            observed_input_tokens=input_tokens if _reported_cache(usage) else 0,
            warm=bool(warm),
            original_messages=_int(opt.get("last_original_messages")),
            sent_messages=_int(opt.get("last_sent_messages")),
            trimmed_messages=_int(opt.get("last_trimmed_messages")),
            dropped_messages=_int(opt.get("last_dropped_messages")),
            rewritten_messages=_int(opt.get("last_rewritten_messages")),
            system_holds=_int(opt.get("last_system_holds")),
            duration_ms=_int_attr(usage, "generation_ms"),
        )
        get_metrics_store().record(row)
    except Exception:
        logger.exception("failed to record coworker cache metric (turn)")


def record_ping(
    *,
    session_key: str | None,
    provider: str,
    model: str,
    usage: Any = None,
    warm_hit: bool = False,
    failure: bool = False,
    now: float | None = None,
) -> None:
    """Persist one keep-alive ping; fail-open."""
    try:
        row = MetricRow(
            at_ms=int((now if now is not None else time.time()) * 1000),
            kind="ping",
            source="system",
            provider=provider,
            model=model,
            input_tokens=_int_attr(usage, "input_tokens"),
            output_tokens=_int_attr(usage, "output_tokens"),
            cache_read_tokens=_int_attr(usage, "cache_read_tokens"),
            cache_write_tokens=_int_attr(usage, "cache_write_tokens"),
            warm_hit=bool(warm_hit),
            failure=bool(failure),
        )
        get_metrics_store().record(row)
    except Exception:
        logger.exception("failed to record coworker cache metric (ping)")


def record_coding_run(
    *,
    task_id: str,
    backend: str = "pi",
    mode: str = "worktree",
    status: str,
    fix_rounds: int = 0,
    settle_continuations: int = 0,
    blocked_calls: int = 0,
    questions: int = 0,
    total_tokens: int = 0,
    cost: float = 0.0,
    duration_ms: int = 0,
    phase_stats: dict[str, Any] | None = None,
    now: float | None = None,
) -> None:
    """Persist one finished coding run; fail-open (never raises into the orchestrator)."""
    try:
        row = CodingRunRow(
            at_ms=int((now if now is not None else time.time()) * 1000),
            task_id=task_id,
            backend=backend,
            mode=mode,
            status=status,
            fix_rounds=fix_rounds,
            settle_continuations=settle_continuations,
            blocked_calls=blocked_calls,
            questions=questions,
            total_tokens=total_tokens,
            cost=cost,
            duration_ms=duration_ms,
            phase_stats_json=json.dumps(phase_stats or {}, ensure_ascii=False),
        )
        get_metrics_store().record_coding_run(row)
    except Exception:
        logger.exception("failed to record coworker coding run")


def coding_runs_payload(*, limit: int = 50) -> dict[str, Any]:
    """Recent finished coding runs for the settings dashboard."""
    try:
        return {"runs": get_metrics_store().coding_runs(limit=limit)}
    except Exception:
        logger.exception("failed to query coworker coding runs")
        return {"runs": []}


def metrics_payload(
    *,
    days: int = 30,
    timezone_name: str | None = None,
    now: Any = None,
) -> dict[str, Any]:
    try:
        return get_metrics_store().metrics_payload(
            days=days,
            timezone_name=timezone_name,
            now=now,
        )
    except Exception:
        logger.exception("failed to query coworker cache metrics")
        return empty_metrics_payload()


__all__ = [
    "CodingRunRow",
    "CoworkerMetricsStore",
    "MetricKind",
    "MetricRow",
    "coding_runs_payload",
    "empty_metrics_payload",
    "get_metrics_store",
    "metrics_payload",
    "metrics_store_path",
    "record_coding_run",
    "record_ping",
    "record_turn",
]
