"""Advice ledger: the structured tail of an advisor reply, parsed and rendered.

The advisor ends a coding-mode reply with one fenced ``json`` block (verdict, open ``must_fix`` /
``verify`` items, ``do_not``, ``pitfalls``, ``next_checkpoint``). The harness strips it from the
text the executor reads, keeps it in the session, pins the open part into the system prompt and
feeds it back to the next consult so the advisor — the only party that closes items — can update it.
Parsing is deliberately forgiving: a reply without a valid block simply leaves the ledger alone.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from nanobot.coworker.transcript import as_dict, as_list

VERDICTS = ("proceed", "revise", "stop")
LIST_KEYS = ("must_fix", "verify", "do_not", "pitfalls")
MAX_ITEMS = 6
MAX_STANDING = 8  # do_not / pitfalls persist across consults
ITEM_MAX_CHARS = 200
CHECKPOINT_MAX_CHARS = 160

_BLOCK_RE = re.compile(r"```(?:json|JSON)?\s*(\{.*?\})\s*```\s*$", re.DOTALL)


def _items(raw: object) -> list[str]:
    out: list[str] = []
    entries: list[Any] = as_list(raw) or []
    for entry in entries:
        text = " ".join(str(entry).split())[:ITEM_MAX_CHARS]
        if text and text.lower() not in {o.lower() for o in out}:
            out.append(text)
    return out[:MAX_ITEMS]


def parse_ledger(text: str) -> tuple[str, dict[str, Any] | None]:
    """Split an advisor reply into ``(guidance, ledger)``; ``ledger`` is None when absent/invalid."""
    stripped = text.rstrip()
    match = _BLOCK_RE.search(stripped)
    if match is None:
        return text, None
    try:
        data = as_dict(json.loads(match.group(1)))
    except ValueError:
        return text, None
    if data is None or not (set(data) & {"verdict", *LIST_KEYS}):
        return text, None
    verdict = str(data.get("verdict") or "proceed").strip().lower()
    checkpoint = data.get("next_checkpoint")
    ledger: dict[str, Any] = {
        "verdict": verdict if verdict in VERDICTS else "proceed",
        "next_checkpoint": (
            " ".join(checkpoint.split())[:CHECKPOINT_MAX_CHARS]
            if isinstance(checkpoint, str) and checkpoint.strip() and checkpoint.strip().lower() != "null"
            else None
        ),
    }
    for key in LIST_KEYS:
        ledger[key] = _items(data.get(key))
    return stripped[: match.start()].rstrip(), ledger


def item_id(text: str) -> str:
    return hashlib.sha1(" ".join(text.lower().split()).encode("utf-8")).hexdigest()[:6]


def merge(previous: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """New open items replace the old ones (absent = closed); standing lists accumulate."""
    merged = dict(new)
    for key in ("do_not", "pitfalls"):
        seen: dict[str, str] = {}
        old: list[Any] = (previous or {}).get(key) or []
        added: list[Any] = new.get(key) or []
        for text in [*old, *added]:
            seen[str(text).lower()] = str(text)
        merged[key] = list(seen.values())[-MAX_STANDING:]
    return merged


def open_count(ledger: dict[str, Any] | None) -> int:
    """Items the executor still has to act on (``must_fix`` + ``verify``)."""
    if not ledger:
        return 0
    return len(ledger.get("must_fix") or []) + len(ledger.get("verify") or [])


def has_content(ledger: dict[str, Any] | None) -> bool:
    return bool(ledger) and (
        open_count(ledger) > 0
        or bool(ledger.get("do_not"))
        or bool(ledger.get("pitfalls"))
        or ledger.get("verdict") in ("revise", "stop")
    )


_LABELS = (
    ("must_fix", "Must fix"),
    ("verify", "Verify"),
    ("do_not", "Do not"),
    ("pitfalls", "Pitfalls"),
)


def render(ledger: dict[str, Any] | None, *, ids: bool = True) -> str:
    """Plain-text ledger for the advisor prompt and the pinned executor section."""
    if not ledger:
        return ""
    lines = [f"Verdict: {ledger.get('verdict') or 'proceed'}"]
    for key, label in _LABELS:
        values: list[Any] = ledger.get(key) or []
        entries = [str(t) for t in values]
        if not entries:
            continue
        lines.append(f"{label}:")
        lines += [f"- [{item_id(t)}] {t}" if ids else f"- {t}" for t in entries]
    if ledger.get("next_checkpoint"):
        lines.append(f"Next checkpoint: {ledger['next_checkpoint']}")
    return "\n".join(lines)
