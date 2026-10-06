"""Interface definition for coding runtimes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from nanobot.coworker.transcript import as_dict


@dataclass(frozen=True)
class BackendStats:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    def diff_from_previous(self, prev: BackendStats) -> BackendStats:
        """Calculate incremental stats given cumulative totals."""
        return BackendStats(
            input_tokens=max(0, self.input_tokens - prev.input_tokens),
            output_tokens=max(0, self.output_tokens - prev.output_tokens),
            thinking_tokens=max(0, self.thinking_tokens - prev.thinking_tokens),
            cache_read_tokens=max(0, self.cache_read_tokens - prev.cache_read_tokens),
            total_tokens=max(0, self.total_tokens - prev.total_tokens),
            cost=max(0.0, self.cost - prev.cost),
        )

    def add(self, other: BackendStats) -> BackendStats:
        return BackendStats(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            thinking_tokens=self.thinking_tokens + other.thinking_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cost=self.cost + other.cost,
        )


def parse_pi_stats(data: object) -> BackendStats:
    stats_dict = as_dict(data) or {}
    tokens = as_dict(stats_dict.get("tokens")) or {}
    cost_val = stats_dict.get("cost")
    cost = float(cost_val) if isinstance(cost_val, (int, float)) else 0.0
    return BackendStats(
        input_tokens=int(tokens.get("input") or 0),
        output_tokens=int(tokens.get("output") or 0),
        thinking_tokens=int(tokens.get("thinking") or 0),
        cache_read_tokens=int(tokens.get("cacheRead") or 0),
        total_tokens=int(tokens.get("total") or 0),
        cost=cost,
    )


@dataclass
class SessionSpec:
    session_file: Path | None = None
    session_dir: Path | None = None
    task_id: str = ""


@dataclass
class ModelSpec:
    provider: str | None = None
    model: str | None = None
    thinking: str | None = None


@dataclass
class RunOutcome:
    status: Literal["succeeded", "error", "timed_out", "aborted", "queued", "handled"]
    response: str = ""
    summary: str = ""
    stats: BackendStats = field(default_factory=BackendStats)
    error: str | None = None
    raw_error_line: str | None = None


class CodingRuntime(ABC):
    """Abstract interface for modern coding runtime harnesses (Pi, Pi Durable, etc.)."""

    @abstractmethod
    async def start(
        self,
        *,
        cwd: Path,
        session: SessionSpec,
        extension: Path | None = None,
        contract_file: Path | None = None,
        model: ModelSpec | None = None,
    ) -> None:
        """Start the runtime child process and initialize session."""
        ...

    @abstractmethod
    async def run_prompt(self, message: str) -> RunOutcome:
        """Execute a prompt turn and await settlement or disposition."""
        ...

    @abstractmethod
    async def steer(self, message: str) -> None:
        """Send steer guidance to active turn."""
        ...

    @abstractmethod
    async def follow_up(self, message: str) -> RunOutcome:
        """Send a follow up prompt within the same or resumed session."""
        ...

    @abstractmethod
    async def abort(self) -> None:
        """Abort active execution immediately."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Gracefully shutdown runtime process."""
        ...
