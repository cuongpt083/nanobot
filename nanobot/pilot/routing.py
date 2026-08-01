"""Deterministic routing engine for pilot mode."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from nanobot.config.schema import PilotConfig, PilotRoutingConfig

RouteClass = Literal["default", "reasoning", "tool_heavy"]
POLICY_VERSION = "2026-07-30.v1"

_MATH_LOGIC_PATTERN = re.compile(
    r"\b(solve|math|calculus|proof|theorem|derive|equation|formula|matrix|integral|differential|logic|algorithm)\b|"
    r"\\(int|sum|sqrt|frac)\b|[=<>+*/^]{2,}",
    re.IGNORECASE,
)

_CODE_PATTERN = re.compile(
    r"```|\b(def\s+\w+|class\s+\w+|import\s+\w+|function\s+\w+|const\s+\w+|var\s+\w+|let\s+\w+|refactor|debug|implement)\b",
    re.IGNORECASE,
)

_MULTI_STEP_PATTERN = re.compile(
    r"\b(step\s+\d+|first,|secondly,|finally,|multi-step|breakdown)\b",
    re.IGNORECASE,
)

_HEAVY_TOOL_NAMES = {"bash", "python_interpreter", "exec", "subagent"}


@dataclass(frozen=True, slots=True)
class RoutingInput:
    channel: str
    content: str
    media_types: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    turn_id: str
    route_class: RouteClass
    primary_preset: str | None
    fallback_presets: tuple[str, ...]
    reason_code: str
    policy_version: str = POLICY_VERSION


def route_turn(
    turn_id: str,
    input_data: RoutingInput,
    config: PilotRoutingConfig | PilotConfig | None = None,
    circuit: Any | None = None,
) -> RoutingDecision:
    """Classify an inbound turn deterministically into a RouteClass and preset targets.

    Classification uses normalized text length, keyword/shape patterns, media presence,
    and available tools. The reason_code is guaranteed to be a fixed enum-like string.
    """
    routing_cfg = getattr(config, "routing", config) if config is not None else None

    content_strip = input_data.content.strip()

    # 1. Tool-heavy check
    if any(t in _HEAVY_TOOL_NAMES for t in input_data.available_tools) or len(input_data.available_tools) > 3:
        route_class: RouteClass = "tool_heavy"
        reason_code = "TOOL_HEAVY_AVAILABLE"
    # 2. Math/Logic check
    elif _MATH_LOGIC_PATTERN.search(content_strip):
        route_class = "reasoning"
        reason_code = "REASONING_MATH_LOGIC"
    # 3. Code check
    elif _CODE_PATTERN.search(content_strip):
        route_class = "reasoning"
        reason_code = "REASONING_CODE_PATTERN"
    # 4. Multi-step check
    elif _MULTI_STEP_PATTERN.search(content_strip):
        route_class = "reasoning"
        reason_code = "REASONING_MULTI_STEP"
    # 5. Long text input check
    elif len(content_strip) > 2000:
        route_class = "reasoning"
        reason_code = "REASONING_LONG_INPUT"
    # 6. Media input check
    elif input_data.media_types:
        route_class = "default"
        reason_code = "DEFAULT_MEDIA_ATTACHMENT"
    # 7. General default
    else:
        route_class = "default"
        reason_code = "DEFAULT_GENERAL"

    primary_preset = route_class
    fallback_presets: tuple[str, ...] = ()

    if routing_cfg is not None and getattr(routing_cfg, "enabled", False):
        class_cfg = getattr(routing_cfg, route_class, None)
        if class_cfg is not None:
            primary_preset = class_cfg.preset
        if hasattr(routing_cfg, "fallbacks") and routing_cfg.fallbacks:
            fallback_presets = tuple(routing_cfg.fallbacks)

    candidates = (primary_preset, *fallback_presets)
    snapshot = _circuit_snapshot(circuit)
    available = tuple(candidate for candidate in candidates if not _candidate_is_open(snapshot.get(candidate)))
    if available:
        primary_preset, *fallbacks = available
        fallback_presets = tuple(fallbacks)
    elif candidates:
        primary_preset = None
        fallback_presets = ()

    return RoutingDecision(
        turn_id=turn_id,
        route_class=route_class,
        primary_preset=primary_preset,
        fallback_presets=fallback_presets,
        reason_code=reason_code,
        policy_version=getattr(routing_cfg, "policy_version", POLICY_VERSION) or POLICY_VERSION,
    )


def _circuit_snapshot(circuit: Any | None) -> Mapping[str, Any]:
    """Capture circuit state once so a decision sees a stable candidate set."""
    if circuit is None:
        return MappingProxyType({})
    raw_snapshot = circuit.snapshot() if callable(getattr(circuit, "snapshot", None)) else circuit
    if not isinstance(raw_snapshot, Mapping):
        return MappingProxyType({})
    return MappingProxyType(dict(raw_snapshot))


def _candidate_is_open(state: Any) -> bool:
    """Accept lightweight circuit state representations without mutating them."""
    if isinstance(state, bool):
        return state
    if isinstance(state, str):
        return state.lower() == "open"
    if isinstance(state, Mapping):
        return bool(state.get("open")) or str(state.get("state", "")).lower() == "open"
    return str(getattr(state, "name", getattr(state, "value", state))).lower() == "open"
