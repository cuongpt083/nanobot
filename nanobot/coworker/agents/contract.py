"""Guest output contract: parse/validate the JSON block teammates must end with."""

from __future__ import annotations

import json
from typing import Any

from nanobot.coworker.workflows.drive import example_from_schema, extract_last_json
from nanobot.coworker.workflows.format import validate_against_schema

GUEST_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["summary", "confidence"],
    "properties": {
        "summary": {"type": "string", "maxLength": 1200},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "confidence": {"enum": ["high", "medium", "low"]},
    },
}

_SUMMARY_MAX = 1200


def contract_example() -> str:
    return example_from_schema(GUEST_OUTPUT_SCHEMA) or (
        '{"summary":"<real value>","confidence":"<one of: high | medium | low>"}'
    )


def parse_guest_contract(text: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Return (payload, errors). Payload is None when JSON is missing or invalid."""
    raw = extract_last_json(text)
    if not raw:
        return None, ["missing a fenced ```json block with summary and confidence"]
    try:
        value = json.loads(raw)
    except ValueError as exc:
        return None, [f"JSON is not parseable: {exc}"]
    errors = validate_against_schema(value, GUEST_OUTPUT_SCHEMA)
    if isinstance(value, dict):
        summary = value.get("summary")
        if isinstance(summary, str) and len(summary) > _SUMMARY_MAX:
            errors.append(f"output.summary: longer than {_SUMMARY_MAX} characters")
    if errors:
        return None, errors
    assert isinstance(value, dict)
    return value, []


def contract_repair_message(errors: list[str]) -> str:
    example = contract_example()
    listed = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous reply did not match the required output contract. "
        "Fix EXACTLY these problems, then end with one fenced ```json block:\n"
        f"{listed}\n\n"
        "COPY THIS FORMAT (replace values with the real ones):\n"
        f"```json\n{example}\n```"
    )
