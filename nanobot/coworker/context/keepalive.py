"""Prompt-cache keep-alive pings (opt-in).

A provider cache READ refreshes the TTL at read price (~0.1×–0.25× input), so
replaying the last real request with a tiny appended user turn shortly before
the TTL elapses re-arms the cache for a fraction of a re-warm. It pays off only
for a few pings after the last real turn, hence the window and ping caps. Pings
never touch the transcript; their responses are discarded.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from nanobot.coworker.context import optimizer
from nanobot.coworker.runtime import spawn_background

PING_PROMPT = "[cache keep-alive] Automated cache-warming ping. Do not call any tools. Reply with exactly: ok"


@dataclass
class _Capture:
    provider: Any
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    max_tokens: int
    temperature: float
    reasoning_effort: str | None
    real_at: float
    pings: int = 0
    failures: int = 0
    spent: dict[str, int] = field(default_factory=dict)
    task: asyncio.Task[Any] | None = None


_captures: dict[str, _Capture] = {}


def capture(
    session_key: str,
    *,
    runtime: Any,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    ttl_s: float,
    window_s: float,
    max_pings: int,
    lead_s: float,
) -> None:
    """Record the last real request and (re)schedule the ping loop."""
    previous = _captures.get(session_key)
    if previous is not None and previous.task is not None:
        previous.task.cancel()
    generation = runtime.generation
    cap = _Capture(
        provider=runtime.provider,
        model=runtime.model,
        messages=messages,
        tools=tools,
        max_tokens=generation.max_tokens,
        temperature=generation.temperature,
        reasoning_effort=generation.reasoning_effort,
        real_at=time.time(),
        spent=previous.spent if previous is not None else {},
    )
    _captures[session_key] = cap
    cap.task = spawn_background(
        _ping_loop(session_key, cap, ttl_s=ttl_s, window_s=window_s, max_pings=max_pings, lead_s=lead_s),
        name=f"coworker-keepalive:{session_key}",
    )


async def _ping_loop(
    session_key: str,
    cap: _Capture,
    *,
    ttl_s: float,
    window_s: float,
    max_pings: int,
    lead_s: float,
) -> None:
    last_touch = cap.real_at
    while cap.pings < max_pings and cap.failures < 2:
        due = last_touch + max(1.0, ttl_s - lead_s)
        if due - cap.real_at > window_s:
            return
        await asyncio.sleep(max(0.0, due - time.time()))
        if time.time() - last_touch > ttl_s:
            return  # cache already expired: re-warming without a user is pure loss
        try:
            response = await cap.provider.chat(
                messages=[*cap.messages, {"role": "user", "content": PING_PROMPT}],
                tools=cap.tools,
                model=cap.model,
                max_tokens=cap.max_tokens,
                temperature=cap.temperature,
                reasoning_effort=cap.reasoning_effort,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            cap.failures += 1
            logger.warning("coworker keep-alive ping failed for {}: {}", session_key, exc)
            continue
        if response.finish_reason == "error":
            cap.failures += 1
            continue
        cap.pings += 1
        last_touch = time.time()
        optimizer.touch(session_key, last_touch)
        usage = response.usage
        cap.spent["pings"] = cap.spent.get("pings", 0) + 1
        if usage is not None:
            cap.spent["input"] = cap.spent.get("input", 0) + int(usage.input_tokens or 0)
            cap.spent["output"] = cap.spent.get("output", 0) + int(usage.output_tokens or 0)
        logger.debug("coworker keep-alive ping {} for {}", cap.pings, session_key)


def status(session_key: str) -> dict[str, Any] | None:
    cap = _captures.get(session_key)
    if cap is None:
        return None
    return {"pings_since_real_turn": cap.pings, "failures": cap.failures, **cap.spent}


def cancel_all() -> None:
    for cap in _captures.values():
        if cap.task is not None:
            cap.task.cancel()
    _captures.clear()
