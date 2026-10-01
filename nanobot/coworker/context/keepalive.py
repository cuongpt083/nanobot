"""Prompt-cache keep-alive pings and status runner.

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
from types import SimpleNamespace
from typing import Any, Literal

from loguru import logger

from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.context import cache_policy, keepalive_state, metrics, optimizer
from nanobot.coworker.context.cache_policy import CacheTtlPolicy, supports_ttl1h
from nanobot.coworker.context.keepalive_state import KeepWarmSetting
from nanobot.coworker.runtime import (
    get_session,
    session_state,
    spawn_background,
    turn_running_since,
)
from nanobot.coworker.transcript import as_dict
from nanobot.providers.base import ProviderCallContext

PING_PROMPT = "[cache keep-alive] Automated cache-warming ping. Do not call any tools. Reply with exactly: ok"
TICK_INTERVAL_S = 15.0


@dataclass
class _Capture:
    session_id: str
    session_key: str
    provider: Any
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    max_tokens: int
    temperature: float
    reasoning_effort: str | None
    real_at: float
    last_touch: float
    pings: int = 0
    failures: int = 0
    last_failure_at: float = 0.0
    last_error: str = ""
    pinging: bool = False
    in_flight: bool = False
    set_at_seen: float = 0.0
    forced_long: bool = False
    spent: dict[str, int] = field(default_factory=dict)


_captures: dict[str, _Capture] = {}
_runner_task: asyncio.Task[Any] | None = None

Action = Literal["none", "kickstart", "rewarm", "ping"]


def evaluate(
    cap: _Capture,
    setting: KeepWarmSetting,
    policy: CacheTtlPolicy | None,
    now: float,
    max_cfg_pings: int = 4,
) -> Action:
    """Evaluate whether a capture is due for a ping, kickstart, or rewarm."""
    if cap.pinging or cap.in_flight or not setting.enabled or policy is None:
        return "none"
    if setting.set_at > cap.last_touch and cap.failures < 2:
        return "kickstart"
    if setting.strategy == "ttl1h" and supports_ttl1h(cap.provider):
        return "none"
    if now - cap.real_at > setting.window_min * 60:
        return "none"
    if cap.pings >= min(policy.ping_cap, max_cfg_pings):
        return "none"
    if cap.failures >= 2 and (now - cap.last_failure_at < 120.0):
        return "none"  # backoff
    expires = cap.last_touch + policy.ttl_s
    if now > expires + 20.0:
        return "rewarm"  # restart window
    if now >= expires - policy.lead_s:
        return "ping"
    return "none"


def mark_in_flight(session_key: str | None, flag: bool) -> None:
    """Prevent pings while a real turn is in flight for this session."""
    if session_key and session_key in _captures:
        _captures[session_key].in_flight = flag


def mark_real_turn(session_key: str | None, *, ttl1h_armed: bool = False) -> None:
    """Record that a real turn completed for this session."""
    if session_key and session_key in _captures:
        cap = _captures[session_key]
        if ttl1h_armed:
            cap.forced_long = True


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
    """Record the last real request and ensure the background tick runner is running."""
    _ = ttl_s, window_s, max_pings, lead_s
    now = time.time()
    previous = _captures.get(session_key)
    generation = runtime.generation
    spent = (
        dict(previous.spent)
        if previous is not None
        else {"pings": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    )
    cap = _Capture(
        session_id=session_key,
        session_key=session_key,
        provider=runtime.provider,
        model=runtime.model,
        messages=messages,
        tools=tools,
        max_tokens=generation.max_tokens,
        temperature=generation.temperature,
        reasoning_effort=generation.reasoning_effort,
        real_at=now,
        last_touch=now,
        spent=spent,
        set_at_seen=previous.set_at_seen if previous is not None else 0.0,
        forced_long=previous.forced_long if previous is not None else False,
    )
    _captures[session_key] = cap
    ensure_runner()


def ensure_runner() -> None:
    """Ensure the background tick runner is active when there are captures."""
    global _runner_task
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    if _runner_task is None or _runner_task.done():
        _runner_task = spawn_background(_runner_loop(), name="coworker-keepalive-runner")


async def _send_ping(
    cap: _Capture,
    *,
    kickstart: bool,
    is_rewarm: bool = False,
    retention: Literal["short", "long"] = "short",
) -> None:
    """Send a single cache-warming ping using the session ID context."""
    cap.pinging = True
    try:
        response = await cap.provider.chat_with_context(
            provider_context=ProviderCallContext(
                session_id=cap.session_id,
                cache_retention=retention,
            ),
            messages=[*cap.messages, {"role": "user", "content": PING_PROMPT}],
            tools=cap.tools,
            model=cap.model,
            max_tokens=cap.max_tokens,
            temperature=cap.temperature,
            reasoning_effort=cap.reasoning_effort,
        )
        if response.finish_reason == "error":
            cap.failures += 1
            cap.last_failure_at = time.time()
            cap.last_error = "finish_reason error"
            return

        now = time.time()
        cap.last_touch = now
        optimizer.touch(cap.session_key, now)
        if kickstart or is_rewarm:
            cap.real_at = now
            cap.pings = 1
        else:
            cap.pings += 1
        if retention == "long":
            cap.forced_long = True
        cap.failures = 0
        cap.last_error = ""

        cap.spent["pings"] = cap.spent.get("pings", 0) + 1
        usage = response.usage
        if usage is not None:
            cap.spent["input"] = cap.spent.get("input", 0) + int(usage.input_tokens or 0)
            cap.spent["output"] = cap.spent.get("output", 0) + int(usage.output_tokens or 0)
            cap.spent["cache_read"] = cap.spent.get("cache_read", 0) + int(usage.cache_read_tokens or 0)
            cap.spent["cache_write"] = cap.spent.get("cache_write", 0) + int(usage.cache_write_tokens or 0)
        logger.debug("coworker keep-alive ping {} for {}", cap.pings, cap.session_key)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        cap.failures += 1
        cap.last_failure_at = time.time()
        cap.last_error = str(exc)[:200]
        logger.warning("coworker keep-alive ping failed for {}: {}", cap.session_key, exc)
    finally:
        cap.pinging = False


async def _runner_loop() -> None:
    try:
        while _captures:
            await asyncio.sleep(TICK_INTERVAL_S)
            if not _captures:
                break
            now = time.time()
            cfg = load_coworker_config()
            for key, cap in list(_captures.items()):
                session = get_session(key)
                setting = (
                    keepalive_state.effective(session)
                    if session
                    else keepalive_state.KeepWarmSetting(
                        enabled=cfg.context.keepalive.enabled,
                        strategy=cfg.context.keepalive.strategy,
                        window_min=cfg.context.keepalive.window_minutes,
                        set_at=0.0,
                        source="global",
                    )
                )
                if setting.enabled and setting.set_at > cap.set_at_seen:
                    cap.set_at_seen = setting.set_at
                    cap.failures = 0
                    cap.last_error = ""

                policy = cache_policy.resolve(
                    cap.provider,
                    cap.model,
                    retention="long" if setting.strategy == "ttl1h" else "short",
                    ttl_override=cfg.context.cache_ttl_seconds,
                )
                action = evaluate(
                    cap, setting, policy, now, max_cfg_pings=cfg.context.keepalive.max_pings
                )
                if action != "none":
                    spawn_background(
                        _send_ping(
                            cap,
                            kickstart=(action in ("kickstart", "rewarm")),
                            is_rewarm=(action == "rewarm"),
                            retention="long" if setting.strategy == "ttl1h" else "short",
                        ),
                        name=f"coworker-keepalive-ping:{key}",
                    )
    except asyncio.CancelledError:
        pass
    finally:
        global _runner_task
        _runner_task = None


def status_for(session: Any) -> dict[str, Any]:
    """Compute detailed keep-warm status for a session."""
    key = getattr(session, "key", "")
    cap = _captures.get(key)
    setting = keepalive_state.effective(session)
    cfg = load_coworker_config()
    now = time.time()

    if cap is not None:
        known = True
        provider_name = getattr(cap.provider, "provider_name", "") or str(type(cap.provider).__name__)
        model = cap.model
        ttl1h_supported = supports_ttl1h(cap.provider)
        effective_strategy = "ttl1h" if (setting.strategy == "ttl1h" and ttl1h_supported) else "ping"
        policy = cache_policy.resolve(
            cap.provider,
            cap.model,
            retention="long" if setting.strategy == "ttl1h" else "short",
            ttl_override=cfg.context.cache_ttl_seconds,
        )
        guaranteed = policy.guaranteed if policy else False
        ttl_s = policy.ttl_s if policy else 300.0
        ping_cap = min(policy.ping_cap, cfg.context.keepalive.max_pings) if policy else 0
        real_turn_at = cap.real_at
        last_touch_at = cap.last_touch
        expires_at = cap.last_touch + ttl_s if policy else None
        parked = cap.failures >= 2 and (now - cap.last_failure_at < 120.0)
        can_ping = (
            setting.enabled
            and policy is not None
            and not parked
            and cap.pings < ping_cap
            and (now - cap.real_at <= setting.window_min * 60)
        )
        next_ping_at = (expires_at - policy.lead_s) if (policy and can_ping and expires_at) else None
        pings = cap.pings
        spent = dict(cap.spent)
        last_error = cap.last_error
        ttl1h_armed = bool(cap.forced_long or (setting.strategy == "ttl1h" and ttl1h_supported and cap.real_at > 0))
        run_active = bool(cap.in_flight or (turn_running_since(key) is not None))
    else:
        # Check persisted cache metadata from session state (survives restart)
        cache_raw: object = session_state(session).get("cache")
        cache_meta = as_dict(cache_raw)
        if cache_meta is not None:
            known = True
            raw_prov: object = cache_meta.get("provider")
            provider_name = str(raw_prov) if isinstance(raw_prov, str) else ""
            raw_model: object = cache_meta.get("model")
            model = str(raw_model) if isinstance(raw_model, str) else ""
            dummy_prov = SimpleNamespace(provider_name=provider_name, backend=provider_name)
            ttl1h_supported = supports_ttl1h(dummy_prov)
            effective_strategy = "ttl1h" if (setting.strategy == "ttl1h" and ttl1h_supported) else "ping"
            policy = cache_policy.resolve(
                dummy_prov,
                model,
                retention="long" if setting.strategy == "ttl1h" else "short",
                ttl_override=cfg.context.cache_ttl_seconds,
            )
            guaranteed = policy.guaranteed if policy else False
            ttl_s = policy.ttl_s if policy else 300.0
            ping_cap = min(policy.ping_cap, cfg.context.keepalive.max_pings) if policy else 0
            raw_call: object = cache_meta.get("last_llm_call_at")
            last_call = float(raw_call) if isinstance(raw_call, (int, float)) else 0.0
            real_turn_at = last_call if last_call > 0 else None
            last_touch_at = last_call if last_call > 0 else None
            expires_at = (last_call + ttl_s) if (last_call > 0 and policy) else None
            parked = False
            can_ping = False
            next_ping_at = None
            pings = 0
            spent = {}
            last_error = ""
            ttl1h_armed = bool(cache_meta.get("ttl1h_armed", False))
            run_active = bool(turn_running_since(key) is not None)
        else:
            known = False
            provider_name = ""
            model = ""
            ttl1h_supported = False
            effective_strategy = setting.strategy
            policy = None
            guaranteed = False
            ttl_s = 300.0
            ping_cap = cfg.context.keepalive.max_pings
            real_turn_at = None
            last_touch_at = None
            expires_at = None
            parked = False
            can_ping = False
            next_ping_at = None
            pings = 0
            spent = {}
            last_error = ""
            ttl1h_armed = False
            run_active = bool(turn_running_since(key) is not None)

    metrics_snap = metrics.snapshot(key)
    raw_last: object = metrics_snap.get("last")
    last_req = as_dict(raw_last)
    raw_input: object = last_req.get("input_tokens") if last_req is not None else None
    est_tokens = int(raw_input) if isinstance(raw_input, int) else 0

    return {
        "known": known,
        "enabled": setting.enabled,
        "source": setting.source,
        "strategy": setting.strategy,
        "effective_strategy": effective_strategy,
        "window_min": setting.window_min,
        "provider": provider_name,
        "model": model,
        "guaranteed": guaranteed,
        "real_turn_at": real_turn_at,
        "last_touch_at": last_touch_at,
        "ttl_s": ttl_s,
        "expires_at": expires_at,
        "ttl1h_supported": ttl1h_supported,
        "ttl1h_armed": ttl1h_armed,
        "pings": pings,
        "ping_cap": ping_cap,
        "can_ping": can_ping,
        "next_ping_at": next_ping_at,
        "est_tokens_per_ping": est_tokens,
        "spent": spent,
        "parked": parked,
        "last_error": last_error,
        "run_active": run_active,
    }


def status(session_key: str) -> dict[str, Any] | None:
    """Legacy helper."""
    cap = _captures.get(session_key)
    if cap is None:
        return None
    return {"pings_since_real_turn": cap.pings, "failures": cap.failures, **cap.spent}


def cancel_all() -> None:
    """Cancel all keep-alive state and runner."""
    global _runner_task
    if _runner_task is not None:
        _runner_task.cancel()
        _runner_task = None
    _captures.clear()
