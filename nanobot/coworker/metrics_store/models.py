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
