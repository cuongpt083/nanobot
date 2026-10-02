"""SQLite persistence and 30-day queries for coworker cache metrics.

Mirrors the shape of :mod:`nanobot.llm_usage.store`: a small synchronous WAL
database shared by gateway threads, with PID-guarded connection reuse, UTC-day
plus row-count pruning, and a memoized payload. Content-free by construction.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from nanobot.coworker.metrics_store.models import MetricRow

SCHEMA_VERSION = 1
MAX_DAYS_RETAINED = 40
MAX_ROWS_RETAINED = 200_000

_METRIC_COLUMNS = (
    "turns",
    "pings",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "observed_input_tokens",
    "ping_input_tokens",
    "ping_output_tokens",
    "ping_cache_read_tokens",
    "ping_cache_write_tokens",
    "warm_turns",
    "warm_hits",
    "ping_failures",
    "original_messages",
    "sent_messages",
    "trimmed_messages",
    "dropped_messages",
    "rewritten_messages",
    "system_holds",
    "duration_ms",
)

_AGGREGATE_SQL = """
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN 1 ELSE 0 END), 0) AS turns,
    COALESCE(SUM(CASE WHEN kind = 'ping' THEN 1 ELSE 0 END), 0) AS pings,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN input_tokens ELSE 0 END), 0) AS input_tokens,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN output_tokens ELSE 0 END), 0) AS output_tokens,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN cache_read_tokens ELSE 0 END), 0) AS cache_read_tokens,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN cache_write_tokens ELSE 0 END), 0) AS cache_write_tokens,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN observed_input_tokens ELSE 0 END), 0) AS observed_input_tokens,
    COALESCE(SUM(CASE WHEN kind = 'ping' THEN input_tokens ELSE 0 END), 0) AS ping_input_tokens,
    COALESCE(SUM(CASE WHEN kind = 'ping' THEN output_tokens ELSE 0 END), 0) AS ping_output_tokens,
    COALESCE(SUM(CASE WHEN kind = 'ping' THEN cache_read_tokens ELSE 0 END), 0) AS ping_cache_read_tokens,
    COALESCE(SUM(CASE WHEN kind = 'ping' THEN cache_write_tokens ELSE 0 END), 0) AS ping_cache_write_tokens,
    COALESCE(SUM(CASE WHEN kind = 'turn' AND warm THEN 1 ELSE 0 END), 0) AS warm_turns,
    COALESCE(SUM(warm_hit), 0) AS warm_hits,
    COALESCE(SUM(failure), 0) AS ping_failures,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN original_messages ELSE 0 END), 0) AS original_messages,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN sent_messages ELSE 0 END), 0) AS sent_messages,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN trimmed_messages ELSE 0 END), 0) AS trimmed_messages,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN dropped_messages ELSE 0 END), 0) AS dropped_messages,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN rewritten_messages ELSE 0 END), 0) AS rewritten_messages,
    COALESCE(SUM(CASE WHEN kind = 'turn' THEN system_holds ELSE 0 END), 0) AS system_holds,
    COALESCE(SUM(duration_ms), 0) AS duration_ms
"""

_INSERT_COLUMNS = (
    "at_ms",
    "kind",
    "source",
    "provider",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "observed_input_tokens",
    "warm",
    "warm_hit",
    "failure",
    "original_messages",
    "sent_messages",
    "trimmed_messages",
    "dropped_messages",
    "rewritten_messages",
    "system_holds",
    "duration_ms",
)


def _zone(timezone_name: str | None) -> timezone | ZoneInfo:
    if not timezone_name:
        return timezone.utc
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _non_negative(value: object) -> int:
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _as_int_row(row: sqlite3.Row) -> dict[str, int]:
    return {key: max(0, int(row[key] or 0)) for key in _METRIC_COLUMNS}


def _empty_totals() -> dict[str, int]:
    return {key: 0 for key in _METRIC_COLUMNS}


def _finalize(values: dict[str, int]) -> dict[str, Any]:
    observed = values["observed_input_tokens"]
    return {
        **values,
        "cache_read_rate": (values["cache_read_tokens"] / observed) if observed else None,
        "saved_messages": max(0, values["original_messages"] - values["sent_messages"]),
    }


class CoworkerMetricsStore:
    """A small synchronous WAL database for coworker cache metrics."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._connection_pid: int | None = None
        self._last_prune_utc_day: int | None = None
        self._writes_since_size_prune = 0
        self._write_version = 0
        self._cached_payload_key: tuple[int, str, str, int, int] | None = None
        self._cached_payload: dict[str, Any] | None = None

    def _connect(self) -> sqlite3.Connection:
        pid = os.getpid()
        if self._connection is not None and self._connection_pid == pid:
            return self._connection
        if self._connection is not None:
            self._connection.close()
            self._cached_payload_key = None
            self._cached_payload = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=0.25,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 250")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.create_function("coworker_local_day", 2, self._local_day, deterministic=True)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS coworker_metrics (
                id INTEGER PRIMARY KEY,
                at_ms INTEGER NOT NULL,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cache_read_tokens INTEGER NOT NULL,
                cache_write_tokens INTEGER NOT NULL,
                observed_input_tokens INTEGER NOT NULL,
                warm INTEGER NOT NULL,
                warm_hit INTEGER NOT NULL,
                failure INTEGER NOT NULL,
                original_messages INTEGER NOT NULL,
                sent_messages INTEGER NOT NULL,
                trimmed_messages INTEGER NOT NULL,
                dropped_messages INTEGER NOT NULL,
                rewritten_messages INTEGER NOT NULL,
                system_holds INTEGER NOT NULL,
                duration_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS coworker_metrics_at_idx
                ON coworker_metrics(at_ms);
            CREATE INDEX IF NOT EXISTS coworker_metrics_kind_at_idx
                ON coworker_metrics(kind, at_ms);
            """
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection = connection
        self._connection_pid = pid
        return connection

    def _read_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=0.25,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 250")
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.create_function("coworker_local_day", 2, self._local_day, deterministic=True)
        return connection

    @staticmethod
    def _local_day(at_ms: object, timezone_name: object) -> str | None:
        if not isinstance(at_ms, int) or not isinstance(timezone_name, str):
            return None
        dt = datetime.fromtimestamp(at_ms / 1000, timezone.utc)
        return dt.astimezone(_zone(timezone_name)).date().isoformat()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
            self._connection = None
            self._connection_pid = None
            self._cached_payload_key = None
            self._cached_payload = None

    def record(self, row: MetricRow) -> None:
        kind = "ping" if row.kind == "ping" else "turn"
        values: tuple[object, ...] = (
            _non_negative(row.at_ms),
            kind,
            (row.source or "user")[:32],
            (row.provider or "")[:120],
            (row.model or "")[:240],
            _non_negative(row.input_tokens),
            _non_negative(row.output_tokens),
            _non_negative(row.cache_read_tokens),
            _non_negative(row.cache_write_tokens),
            _non_negative(row.observed_input_tokens),
            int(bool(row.warm)),
            int(bool(row.warm_hit)),
            int(bool(row.failure)),
            _non_negative(row.original_messages),
            _non_negative(row.sent_messages),
            _non_negative(row.trimmed_messages),
            _non_negative(row.dropped_messages),
            _non_negative(row.rewritten_messages),
            _non_negative(row.system_holds),
            _non_negative(row.duration_ms),
        )
        placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
        with self._lock:
            connection = self._connect()
            connection.execute(
                f"INSERT INTO coworker_metrics ({', '.join(_INSERT_COLUMNS)}) "
                f"VALUES ({placeholders})",
                values,
            )
            self._write_version += 1
            self._cached_payload_key = None
            self._cached_payload = None
            self._prune_if_due(connection)

    def _prune_if_due(self, connection: sqlite3.Connection) -> None:
        utc_day = int(time.time() // 86_400)
        self._writes_since_size_prune += 1
        prune_age = self._last_prune_utc_day != utc_day
        prune_size = self._writes_since_size_prune >= 1_024
        if not prune_age and not prune_size:
            return
        if prune_age:
            cutoff_ms = int(
                (datetime.now(timezone.utc) - timedelta(days=MAX_DAYS_RETAINED)).timestamp() * 1000
            )
            connection.execute("DELETE FROM coworker_metrics WHERE at_ms < ?", (cutoff_ms,))
        connection.execute(
            """
            DELETE FROM coworker_metrics
            WHERE id <= COALESCE((
                SELECT id FROM coworker_metrics ORDER BY id DESC LIMIT 1 OFFSET ?
            ), -1)
            """,
            (MAX_ROWS_RETAINED,),
        )
        self._last_prune_utc_day = utc_day
        self._writes_since_size_prune = 0

    def count(self) -> int:
        with self._lock:
            row = (
                self._connect()
                .execute("SELECT COUNT(*) AS count FROM coworker_metrics")
                .fetchone()
            )
        return int(row["count"] if row is not None else 0)

    def _aggregate(
        self,
        *,
        connection: sqlite3.Connection,
        start_ms: int,
        end_ms: int,
        group_by: str | None = None,
        kind: str | None = None,
    ) -> list[sqlite3.Row]:
        selected = f"{group_by}, " if group_by else ""
        where = "at_ms >= ? AND at_ms < ?"
        params: list[object] = [start_ms, end_ms]
        if kind is not None:
            where += " AND kind = ?"
            params.append(kind)
        query = f"SELECT {selected}{_AGGREGATE_SQL} FROM coworker_metrics WHERE {where}"
        if group_by:
            query += f" GROUP BY {group_by}"
        return list(connection.execute(query, params).fetchall())

    def _daily_rows(
        self,
        *,
        connection: sqlite3.Connection,
        start_ms: int,
        end_ms: int,
        timezone_name: str,
    ) -> list[dict[str, Any]]:
        query = f"""
            SELECT coworker_local_day(at_ms, ?) AS date, {_AGGREGATE_SQL}
            FROM coworker_metrics
            WHERE at_ms >= ? AND at_ms < ?
            GROUP BY date
            ORDER BY date
        """
        rows = connection.execute(query, (timezone_name, start_ms, end_ms)).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            day = cast(str | None, row["date"])
            if day is None:
                continue
            out.append({"date": day, **_finalize(_as_int_row(row))})
        return out

    @staticmethod
    def _midnight_ms(value: date, zone: timezone | ZoneInfo) -> int:
        return int(datetime.combine(value, datetime.min.time(), tzinfo=zone).timestamp() * 1000)

    def metrics_payload(
        self,
        *,
        days: int = 30,
        timezone_name: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        zone = _zone(timezone_name)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        today = current.astimezone(zone).date()
        safe_days = max(1, days)
        zone_name = getattr(zone, "key", "UTC")

        with self._lock:
            data_version_row = self._connect().execute("PRAGMA data_version").fetchone()
            data_version = int(data_version_row[0]) if data_version_row is not None else 0
            write_version = self._write_version
            cache_key = (safe_days, zone_name, today.isoformat(), write_version, data_version)
            if self._cached_payload_key == cache_key and self._cached_payload is not None:
                return deepcopy(self._cached_payload)

        connection = self._read_connection()
        try:
            connection.execute("BEGIN")
            end_ms = self._midnight_ms(today + timedelta(days=1), zone)
            retained_start_ms = self._midnight_ms(today - timedelta(days=MAX_DAYS_RETAINED - 1), zone)
            daily = self._daily_rows(
                connection=connection,
                start_ms=retained_start_ms,
                end_ms=end_ms,
                timezone_name=zone_name,
            )

            requested_start = today - timedelta(days=safe_days - 1)
            window_start_ms = self._midnight_ms(requested_start, zone)
            visible_days = [row for row in daily if row["date"] >= requested_start.isoformat()]
            totals = _empty_totals()
            for row in visible_days:
                for key in _METRIC_COLUMNS:
                    totals[key] += int(row.get(key) or 0)
            total = _finalize(totals)

            source_rows = self._aggregate(
                connection=connection,
                start_ms=window_start_ms,
                end_ms=end_ms,
                group_by="source",
                kind="turn",
            )
            sources_30d = [
                {"source": str(row["source"]), **_finalize(_as_int_row(row))}
                for row in source_rows
            ]

            latest = connection.execute(
                "SELECT MAX(at_ms) AS updated_at_ms FROM coworker_metrics"
            ).fetchone()
            updated_at_ms = int(latest["updated_at_ms"] or 0) if latest is not None else 0

            payload: dict[str, Any] = {
                "days": visible_days,
                "total_turns_30d": total["turns"],
                "total_pings_30d": total["pings"],
                "input_tokens_30d": total["input_tokens"],
                "output_tokens_30d": total["output_tokens"],
                "cache_read_tokens_30d": total["cache_read_tokens"],
                "cache_write_tokens_30d": total["cache_write_tokens"],
                "observed_input_tokens_30d": total["observed_input_tokens"],
                "cache_read_rate_30d": total["cache_read_rate"],
                "ping_input_tokens_30d": total["ping_input_tokens"],
                "ping_output_tokens_30d": total["ping_output_tokens"],
                "ping_cache_read_tokens_30d": total["ping_cache_read_tokens"],
                "ping_cache_write_tokens_30d": total["ping_cache_write_tokens"],
                "warm_turns_30d": total["warm_turns"],
                "warm_hits_30d": total["warm_hits"],
                "ping_failures_30d": total["ping_failures"],
                "original_messages_30d": total["original_messages"],
                "sent_messages_30d": total["sent_messages"],
                "saved_messages_30d": total["saved_messages"],
                "trimmed_messages_30d": total["trimmed_messages"],
                "dropped_messages_30d": total["dropped_messages"],
                "rewritten_messages_30d": total["rewritten_messages"],
                "system_holds_30d": total["system_holds"],
                "sources_30d": sources_30d,
                "updated_at": (
                    datetime.fromtimestamp(updated_at_ms / 1000, timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                    if updated_at_ms
                    else None
                ),
            }
        finally:
            connection.close()

        with self._lock:
            latest_version_row = self._connect().execute("PRAGMA data_version").fetchone()
            latest_version = int(latest_version_row[0]) if latest_version_row is not None else 0
            if self._write_version == write_version and latest_version == data_version:
                self._cached_payload_key = cache_key
                self._cached_payload = payload
        return deepcopy(payload)
