"""Provider-reported prompt-cache usage per session (in memory, for the WebUI inspector).

The optimizer describes what nanobot *sent*; this records what the provider *reported back*:
how much of each request's input was served from cache and how much was newly written.
``None`` cache counts mean the provider did not report that metric, so they are excluded from
the hit-rate denominator rather than counted as misses.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

RECENT_CALLS = 20
MAX_SESSIONS = 200


@dataclass(frozen=True)
class CallSample:
    at: float
    input_tokens: int
    output_tokens: int
    cache_read: int | None
    cache_write: int | None

    @property
    def reported(self) -> bool:
        return self.cache_read is not None or self.cache_write is not None

    def hit_rate(self) -> float | None:
        if not self.reported or self.input_tokens <= 0:
            return None
        return (self.cache_read or 0) / self.input_tokens


@dataclass
class _Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    observed_input: int = 0  # input of calls whose provider reported cache counts
    recent: deque[CallSample] = field(default_factory=lambda: deque(maxlen=RECENT_CALLS))


_sessions: dict[str, _Totals] = {}


def record(session_key: str | None, usage: Any, *, now: float | None = None) -> None:
    """Add one LLM call's ``LLMUsage`` (ignored when absent or malformed)."""
    if not session_key or usage is None:
        return
    input_tokens = getattr(usage, "input_tokens", None)
    if not isinstance(input_tokens, int) or input_tokens <= 0:
        return
    read = getattr(usage, "cache_read_tokens", None)
    write = getattr(usage, "cache_write_tokens", None)
    sample = CallSample(
        at=now if now is not None else time.time(),
        input_tokens=input_tokens,
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read=read if isinstance(read, int) else None,
        cache_write=write if isinstance(write, int) else None,
    )
    totals = _sessions.get(session_key)
    if totals is None:
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))
        totals = _sessions[session_key] = _Totals()
    totals.calls += 1
    totals.input_tokens += sample.input_tokens
    totals.output_tokens += sample.output_tokens
    if sample.reported:
        totals.cache_read += sample.cache_read or 0
        totals.cache_write += sample.cache_write or 0
        totals.observed_input += sample.input_tokens
    totals.recent.append(sample)


def snapshot(session_key: str | None) -> dict[str, Any]:
    totals = _sessions.get(session_key) if session_key else None
    if totals is None or not totals.recent:
        return {
            "calls": 0,
            "reported": False,
            "hit_rate": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "last": None,
            "recent_hit_rates": [],
        }
    last = totals.recent[-1]
    return {
        "calls": totals.calls,
        "reported": totals.observed_input > 0,
        "hit_rate": (totals.cache_read / totals.observed_input) if totals.observed_input else None,
        "input_tokens": totals.input_tokens,
        "output_tokens": totals.output_tokens,
        "cache_read_tokens": totals.cache_read,
        "cache_write_tokens": totals.cache_write,
        "last": {
            "at": last.at,
            "input_tokens": last.input_tokens,
            "cache_read_tokens": last.cache_read,
            "cache_write_tokens": last.cache_write,
            "hit_rate": last.hit_rate(),
        },
        "recent_hit_rates": [s.hit_rate() for s in totals.recent],
    }


def reset(session_key: str | None = None) -> None:
    if session_key is None:
        _sessions.clear()
    else:
        _sessions.pop(session_key, None)
