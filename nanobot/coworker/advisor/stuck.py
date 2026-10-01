"""Mechanical stuck detection for tool calls in the coworker harness."""

from __future__ import annotations

import re
from typing import Any, cast

_PATH_RE = re.compile(r"[a-zA-Z]:\\[^\s:\"']+|/(?:[^\s:\"']+/)+[^\s:\"']*")
_HEX_RE = re.compile(r"0x[0-9a-fA-F]+")
_TIME_RE = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?")
_NUM_RE = re.compile(r"\b\d+\b")
_EXIT_CODE_RE = re.compile(r"Exit code:\s*(-?\d+)", re.IGNORECASE)


def failure_signature(tool_name: str, args: dict[str, Any], result: Any) -> str | None:
    """Extract a normalized failure signature, or None if the result is not an error."""
    is_err = getattr(result, "is_error", False) is True
    if isinstance(result, BaseException):
        is_err = True
    elif isinstance(result, dict) and cast("dict[str, Any]", result).get("is_error") is True:
        is_err = True

    raw_text = ""
    if isinstance(result, BaseException):
        raw_text = f"{type(result).__name__}: {result}"
    elif isinstance(result, dict):
        mapping = cast("dict[str, Any]", result)
        raw_text = str(mapping.get("content") or mapping.get("error") or "")
    elif hasattr(result, "content"):
        raw_text = str(getattr(result, "content"))
    else:
        raw_text = str(result) if result is not None else ""

    if tool_name in {"exec", "exec_session"}:
        match = _EXIT_CODE_RE.search(raw_text)
        if match is not None:
            code = int(match.group(1))
            if code != 0:
                is_err = True
            else:
                return None  # Exit code 0 is explicitly not an error
        elif not is_err:
            return None

        cmd = args.get("command") or args.get("cmd") or ""
        norm_cmd = " ".join(str(cmd).split())
        return f"exec:{norm_cmd}"

    if not is_err:
        return None

    first_line = ""
    for line in raw_text.splitlines():
        line = line.strip()
        if line:
            first_line = line
            break

    cleaned = _TIME_RE.sub("", first_line)
    cleaned = _HEX_RE.sub("", cleaned)
    cleaned = _PATH_RE.sub("", cleaned)
    cleaned = _NUM_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    return f"{tool_name}:{cleaned}"[:160]


class StuckTracker:
    """Tracks failure signatures within a run; triggers on repeat failure."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def record(self, signature: str | None) -> bool:
        """Record a failure signature; return True on the 2nd occurrence since reset."""
        if not signature:
            return False
        count = self._counts.get(signature, 0) + 1
        self._counts[signature] = count
        return count == 2

    def reset(self) -> None:
        """Clear recorded failures (called when the advisor tool runs)."""
        self._counts.clear()
