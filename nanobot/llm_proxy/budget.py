"""Per-key token budget tracking for Nanobot LLM Proxy."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.config.paths import get_runtime_subdir
from nanobot.llm_proxy.keys import ProxyApiKey


def get_period_key(period: str, dt: datetime | None = None) -> str:
    """Return the bucket key for a budget period window."""
    now = dt or datetime.now()
    if period == "5h":
        bucket = (now.hour // 5) * 5
        return f"{now.strftime('%Y-%m-%d')}T{bucket:02d}"
    elif period == "daily":
        return now.strftime("%Y-%m-%d")
    elif period == "weekly":
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    elif period == "monthly":
        return now.strftime("%Y-%m")
    elif period == "lifetime":
        return "lifetime"
    return "none"


class BudgetTracker:
    """Tracks token consumption per key across calendar/fixed windows."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self.dir = storage_dir or get_runtime_subdir("llm_proxy")
        self._usage: dict[str, dict[str, Any]] = {}
        self._load()

    @property
    def _file(self) -> Path:
        return self.dir / "usage.json"

    def _load(self) -> None:
        if self._file.is_file():
            try:
                self._usage = json.loads(self._file.read_text(encoding="utf-8"))
            except Exception:
                self._usage = {}
        else:
            self._usage = {}

    def _save(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._usage, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_status(self, key: ProxyApiKey) -> dict[str, Any]:
        """Return the current budget status for an API key."""
        if not key.budget_tokens or key.budget_period == "none":
            return {
                "enforced": False,
                "used": 0,
                "limit": None,
                "remaining": None,
                "period": key.budget_period,
                "period_key": "none",
            }

        period_key = get_period_key(key.budget_period)
        entry = self._usage.get(key.id, {})
        current_used = entry.get("tokens", 0) if entry.get("period_key") == period_key else 0
        limit = key.budget_tokens
        remaining = max(0, limit - current_used)

        return {
            "enforced": True,
            "used": current_used,
            "limit": limit,
            "remaining": remaining,
            "period": key.budget_period,
            "period_key": period_key,
        }

    def check_budget(self, key: ProxyApiKey) -> tuple[bool, dict[str, Any]]:
        """Return (allowed, status). If False, caller should respond 429."""
        status = self.get_status(key)
        if not status["enforced"]:
            return True, status
        allowed = status["used"] < (status["limit"] or math.inf)
        return allowed, status

    def commit_tokens(self, key: ProxyApiKey, tokens: int) -> None:
        """Add consumed tokens to the key's current bucket."""
        if not key.budget_tokens or key.budget_period == "none" or tokens <= 0:
            return
        period_key = get_period_key(key.budget_period)
        entry = self._usage.get(key.id, {})
        if entry.get("period_key") == period_key:
            entry["tokens"] = entry.get("tokens", 0) + tokens
        else:
            entry = {"period_key": period_key, "tokens": tokens}
        self._usage[key.id] = entry
        self._save()
