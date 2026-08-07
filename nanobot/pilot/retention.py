"""Retention service for automated dry-run planning and pruning of old turns."""

from __future__ import annotations

import time
from typing import Any

from nanobot.pilot.store import SQLitePilotStore


class RetentionService:
    """Calculates retention policy candidates and executes pruning."""

    def __init__(self, store: SQLitePilotStore, retention_days: int = 90) -> None:
        self.store = store
        self.retention_days = retention_days

    def plan(self, now_ms: int | None = None) -> dict[str, Any]:
        """Generate a dry-run plan of rows eligible for retention pruning."""
        if now_ms is None:
            now_ms = int(time.time() * 1000)

        candidates = self.store.count_retention_candidates(now_ms, self.retention_days)
        return {
            "now_ms": now_ms,
            "retention_days": self.retention_days,
            "eligible_old_turns": candidates.get("old_turns", 0),
        }

    def apply(self, plan: dict[str, Any]) -> dict[str, int]:
        """Apply retention plan (stubbed count for now)."""
        return {"pruned_turns": 0}
