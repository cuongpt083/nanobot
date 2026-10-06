"""Durable metric rows for the coworker cache/keep-warm/optimize layers.

One row per agent iteration (``kind="turn"``) or per keep-alive ping (``kind="ping"``).
Content-free: session keys are never stored, only the coarse usage source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MetricKind = Literal["turn", "ping"]


@dataclass(frozen=True, slots=True)
class MetricRow:
    at_ms: int
    kind: MetricKind
    source: str = "user"
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    observed_input_tokens: int = 0
    warm: bool = False
    warm_hit: bool = False
    failure: bool = False
    original_messages: int = 0
    sent_messages: int = 0
    trimmed_messages: int = 0
    dropped_messages: int = 0
    rewritten_messages: int = 0
    system_holds: int = 0
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class CodingRunRow:
    """One finished coding task: outcome, review/fix rounds, blocks, questions, per-phase cost."""

    at_ms: int
    task_id: str = ""
    backend: str = "pi"
    mode: str = "worktree"
    status: str = "succeeded"
    fix_rounds: int = 0
    settle_continuations: int = 0
    blocked_calls: int = 0
    questions: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    duration_ms: int = 0
    phase_stats_json: str = "{}"
