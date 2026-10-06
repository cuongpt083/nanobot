"""Read nanobot-bridge entries returned by Pi's ``get_entries`` RPC.

Pi stores extension data as ``CustomEntry`` records:
``{"id": ..., "parentId": ..., "type": "custom", "customType": "...", "data": {...}}``.
"""

from __future__ import annotations

from typing import Any, cast

REPORT = "nanobot_report"
BLOCK = "nanobot_block"
GATE = "nanobot_gate"


def _custom_data(entry: dict[str, Any], custom_type: str) -> dict[str, Any] | None:
    if entry.get("type") != "custom" or entry.get("customType") != custom_type:
        return None
    data = entry.get("data")
    if data is None:
        data = entry.get("params") or entry.get("payload")
    if isinstance(data, dict):
        return cast("dict[str, Any]", data)
    return {}


def extract_report(
    entries: list[dict[str, Any]], *, kind: str | None = None
) -> dict[str, Any] | None:
    """Return the most recent ``report_result`` payload, optionally filtered by ``kind``."""
    found: dict[str, Any] | None = None
    for entry in entries:
        data = _custom_data(entry, REPORT)
        if data is None:
            continue
        if kind is not None and data.get("kind") != kind:
            continue
        found = data
    return found


def count_blocks(entries: list[dict[str, Any]]) -> int:
    """Count policy blocks recorded by the extension."""
    return sum(1 for entry in entries if _custom_data(entry, BLOCK) is not None)


def extract_gate(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the most recent acceptance-gate record, if any."""
    found: dict[str, Any] | None = None
    for entry in entries:
        data = _custom_data(entry, GATE)
        if data is not None:
            found = data
    return found
