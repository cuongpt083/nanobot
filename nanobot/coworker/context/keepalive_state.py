"""Per-session keep-warm settings and inheritance."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.runtime import session_state
from nanobot.coworker.transcript import as_dict

Strategy = Literal["ping", "ttl1h"]
DEFAULT_WINDOW_MIN = 30
MIN_WINDOW_MIN = 1
MAX_WINDOW_MIN = 120


@dataclass(frozen=True)
class KeepWarmSetting:
    enabled: bool
    strategy: Strategy
    window_min: int
    set_at: float
    source: Literal["session", "global"]


def clamp_window(v: int | None) -> int:
    """Clamp keep-warm window to [1..120] minutes with default 30."""
    if v is None:
        return DEFAULT_WINDOW_MIN
    try:
        val = int(v)
    except (ValueError, TypeError):
        return DEFAULT_WINDOW_MIN
    return max(MIN_WINDOW_MIN, min(MAX_WINDOW_MIN, val))


def _slot(session: Any) -> dict[str, Any]:
    state = session_state(session)
    slot = as_dict(state.get("keepalive"))
    if slot is None:
        slot = {}
        state["keepalive"] = slot
    return slot


def effective(session: Any) -> KeepWarmSetting:
    """Return the effective keep-warm setting for a session.

    If the session has overridden keepalive settings, use them;
    otherwise inherit from global CoworkerConfig.context.keepalive.
    """
    cfg = load_coworker_config().context.keepalive
    slot = _slot(session)
    enabled_override = slot.get("enabled")
    if isinstance(enabled_override, bool):
        strategy_raw = slot.get("strategy")
        strategy: Strategy = "ttl1h" if strategy_raw == "ttl1h" else "ping"
        window = clamp_window(slot.get("window_min"))
        set_at = float(slot.get("set_at", 0.0) or 0.0)
        return KeepWarmSetting(
            enabled=enabled_override,
            strategy=strategy,
            window_min=window,
            set_at=set_at,
            source="session",
        )
    return KeepWarmSetting(
        enabled=bool(cfg.enabled),
        strategy="ttl1h" if cfg.strategy == "ttl1h" else "ping",
        window_min=clamp_window(cfg.window_minutes),
        set_at=0.0,
        source="global",
    )


def apply(
    session: Any,
    *,
    enabled: bool | None,
    strategy: Strategy | None = None,
    window_min: int | None = None,
    now: float | None = None,
) -> KeepWarmSetting:
    """Update or clear session-level keep-warm overrides.

    enabled=None removes the session override and reverts to global.
    When enabled is bool, records set_at timestamp.
    """
    slot = _slot(session)
    if enabled is None:
        slot.pop("enabled", None)
        slot.pop("strategy", None)
        slot.pop("window_min", None)
        slot.pop("set_at", None)
    else:
        slot["enabled"] = bool(enabled)
        if strategy in ("ping", "ttl1h"):
            slot["strategy"] = strategy
        elif "strategy" not in slot:
            cfg = load_coworker_config().context.keepalive
            slot["strategy"] = "ttl1h" if cfg.strategy == "ttl1h" else "ping"
        if window_min is not None:
            slot["window_min"] = clamp_window(window_min)
        elif "window_min" not in slot:
            cfg = load_coworker_config().context.keepalive
            slot["window_min"] = clamp_window(cfg.window_minutes)
        slot["set_at"] = time.time() if now is None else float(now)
    return effective(session)
