"""Sensitive-safe metric counters and snapshot containers."""

from __future__ import annotations

import threading


class PilotMetrics:
    """Thread-safe metrics registry with safe labels only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.capture_hook_errors_total = 0
        self.queue_drops_by_kind: dict[str, int] = {}
        self.events_persisted_by_kind: dict[str, int] = {}

    def inc_hook_error(self) -> None:
        with self._lock:
            self.capture_hook_errors_total += 1

    def inc_queue_drop(self, kind: str) -> None:
        with self._lock:
            self.queue_drops_by_kind[kind] = self.queue_drops_by_kind.get(kind, 0) + 1

    def inc_events_persisted(self, kind: str, count: int = 1) -> None:
        with self._lock:
            self.events_persisted_by_kind[kind] = self.events_persisted_by_kind.get(kind, 0) + count

    def snapshot(self) -> dict[str, int | dict[str, int]]:
        with self._lock:
            return {
                "capture_hook_errors_total": self.capture_hook_errors_total,
                "queue_drops_by_kind": dict(self.queue_drops_by_kind),
                "events_persisted_by_kind": dict(self.events_persisted_by_kind),
            }


# Global metrics singleton instance
pilot_metrics = PilotMetrics()
