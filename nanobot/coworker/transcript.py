"""Helpers over nanobot's OpenAI-style message dicts."""

from __future__ import annotations

import json
from typing import Any, cast

# Injected harness turns start with one of these; they are plumbing, never the
# genuine human request (advisor run anchoring, distill, trimming guards).
AUTO_MARKERS = (
    "[auto-advisor-review]",
    "[auto-room]",
    "[auto-workflow:",
)


def as_dict(value: object) -> dict[str, Any] | None:
    """Narrow a JSON-ish value to a string-keyed dict (keys are str in every JSON source)."""
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def as_list(value: object) -> list[Any] | None:
    return cast(list[Any], value) if isinstance(value, list) else None


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for raw in as_list(content) or []:
        block = as_dict(raw)
        if block is None:
            continue
        text = block.get("text")
        if isinstance(text, str) and block.get("type") in (None, "text", "input_text", "output_text"):
            parts.append(text)
    return "\n".join(parts)


def message_text(message: dict[str, Any]) -> str:
    return content_text(message.get("content"))


def tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for raw in as_list(message.get("tool_calls")) or [] if (c := as_dict(raw)) is not None]


def tool_call_name(call: dict[str, Any]) -> str:
    fn = as_dict(call.get("function"))
    name = fn.get("name") if fn is not None else None
    return name if isinstance(name, str) else str(call.get("name") or "")


def tool_call_arguments(call: dict[str, Any]) -> str:
    fn = as_dict(call.get("function"))
    args: object = fn.get("arguments") if fn is not None else call.get("arguments")
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args if args is not None else {}, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def is_auto_turn(text: str) -> bool:
    stripped = text.lstrip()
    return any(stripped.startswith(marker) for marker in AUTO_MARKERS)


def is_genuine_user(message: dict[str, Any]) -> bool:
    if message.get("role") != "user":
        return False
    text = message_text(message)
    return bool(text.strip()) and not is_auto_turn(text)


def user_turn_starts(messages: list[dict[str, Any]]) -> list[int]:
    """Indices of user messages; tool results never open a turn in this format."""
    return [i for i, m in enumerate(messages) if m.get("role") == "user"]


def elide(text: str, max_chars: int, head: int, tail: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = len(text) - head - tail
    return f"{text[:head]}\n…[elided {cut} chars]…\n{text[-tail:]}"
