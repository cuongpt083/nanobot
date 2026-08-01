from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from nanobot.bus.outbound_events import ProgressEvent

_POLICY_KEYS = frozenset(
    {
        "arguments",
        "error",
        "providererror",
        "reasoning",
        "reasoningdelta",
        "reasoningend",
        "reasoningcontent",
        "thinkingblocks",
        "toolarguments",
        "toolevents",
        "fileeditevents",
    }
)
_THINK_BLOCK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)
_REDACTION_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
        r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    re.compile(r"sk-[a-zA-Z0-9_-]+"),
    re.compile(
        r"(?:Bearer|API[-_ ]?key|cookie|token|private[-_ ]?key)\s*(?::|=)?\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"https?://[^:\s]+:[^@\s]+@"),
    re.compile(r"[a-zA-Z]:\\[^\s]+"),
    re.compile(r"/(?:var|etc|usr|home|root|tmp|proc|sys)/[^\s]+"),
    re.compile(r"Exception:\s*.*", re.IGNORECASE),
)


def _normalized_metadata_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _sanitize_string(value: str) -> str:
    sanitized = _THINK_BLOCK.sub("", value)
    for pattern in _REDACTION_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)
    return sanitized


def _sanitize_value(value: Any, blocked: list[str], path: str = "") -> tuple[Any, bool]:
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        changed = False
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if _normalized_metadata_key(key) in _POLICY_KEYS:
                blocked.append(child_path)
                changed = True
                continue
            sanitized_child, child_changed = _sanitize_value(child, blocked, child_path)
            sanitized[key] = sanitized_child
            changed = changed or child_changed
        return sanitized, changed
    if isinstance(value, list):
        sanitized_list: list[Any] = []
        changed = False
        for index, child in enumerate(value):
            sanitized_child, child_changed = _sanitize_value(child, blocked, f"{path}[{index}]")
            sanitized_list.append(sanitized_child)
            changed = changed or child_changed
        return sanitized_list, changed
    if isinstance(value, tuple):
        sanitized_items, changed = _sanitize_value(list(value), blocked, path)
        return tuple(sanitized_items), changed
    if isinstance(value, str):
        sanitized = _sanitize_string(value)
        return sanitized, sanitized != value
    return value, False


def _safe_progress_event_fields(event: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    version = event.get("version")
    if isinstance(version, int) and not isinstance(version, bool):
        safe["version"] = version
    phase = event.get("phase")
    if isinstance(phase, str) and phase in {"start", "end", "error"}:
        safe["phase"] = phase
    for field in ("call_id", "name"):
        value = event.get(field)
        if isinstance(value, str):
            safe[field] = value
    return safe


def sanitize_progress_event(event: Any) -> Any:
    """Return a presentation-safe progress event without tool payload data."""
    if not isinstance(event, ProgressEvent):
        return event
    tool_events = (
        [_safe_progress_event_fields(item) for item in event.tool_events if isinstance(item, dict)]
        if event.tool_events is not None
        else None
    )
    file_edit_events: list[dict[str, Any]] | None = None
    if event.file_edit_events is not None:
        file_edit_events = []
        for item in event.file_edit_events:
            if not isinstance(item, dict):
                continue
            safe = _safe_progress_event_fields(item)
            if "path" in item:
                safe["path"] = "[REDACTED]"
            file_edit_events.append(safe)
    return replace(event, tool_events=tool_events, file_edit_events=file_edit_events)


@dataclass(frozen=True, slots=True)
class PresentationResult:
    content: str
    metadata: dict[str, Any]
    blocked_fields: tuple[str, ...]
    leak_prevented: bool


class PresentationPolicy:
    """Pure outbound content/metadata sanitizer and event allow-policy."""

    def __init__(self, on_leak_prevented: Callable[[], None] | None = None):
        self._on_leak_prevented = on_leak_prevented

    def permits_event(self, event: Any, show_reasoning: bool) -> bool:
        if not show_reasoning and isinstance(event, ProgressEvent):
            if event.reasoning or event.reasoning_delta or event.reasoning_end:
                return False
        return True

    def sanitize_event(self, event: Any) -> Any:
        return sanitize_progress_event(event)

    def sanitize(self, content: str, metadata: dict[str, Any]) -> PresentationResult:
        blocked: list[str] = []
        original_content = content
        content = _sanitize_string(content)
        sanitized_metadata, metadata_changed = _sanitize_value(metadata, blocked)

        leak_prevented = metadata_changed or content != original_content
        if leak_prevented and self._on_leak_prevented:
            self._on_leak_prevented()

        return PresentationResult(
            content=content,
            metadata=sanitized_metadata,
            blocked_fields=tuple(blocked),
            leak_prevented=leak_prevented,
        )
