"""Advice ledger: the structured tail of an advisor reply, parsed and rendered.

The advisor ends a coding-mode reply with one fenced ``json`` block (verdict, open ``must_fix`` /
``verify`` items, ``do_not``, ``pitfalls``, ``next_checkpoint``). The harness strips it from the
text the executor reads, keeps it in the session, pins the open part into the system prompt and
feeds it back to the next consult so the advisor — the only party that closes items — can update it.
Parsing is deliberately forgiving: a reply without a valid block simply leaves the ledger alone.

With ``advisor.output_template`` the block may also carry ``goal``, ``done_when`` (the definition of
done), ``steps`` and ``unverified``. Unlike ``must_fix`` / ``verify``, ``goal`` and ``done_when`` are
targets, not open issues: an item that is missing from a later reply is *not* closed, so silence
keeps them and only the advisor changes an item's ``status``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from nanobot.coworker.transcript import as_dict, as_list

VERDICTS = ("proceed", "revise", "stop")
LIST_KEYS = ("must_fix", "verify", "do_not", "pitfalls")
TEMPLATE_KEYS = ("goal", "done_when", "steps", "unverified")
DONE_STATUSES = ("open", "met", "unknown")
MAX_ITEMS = 6
MAX_STANDING = 8  # do_not / pitfalls persist across consults
ITEM_MAX_CHARS = 200
CHECKPOINT_MAX_CHARS = 160
GOAL_MAX_CHARS = 200
DONE_MAX_ITEMS = 6
DONE_MAX_CHARS = 160
STEP_MAX_ITEMS = 8

_BLOCK_RE = re.compile(r"```(?:json|JSON)?\s*(\{.*?\})\s*```\s*$", re.DOTALL)


def _items(raw: object) -> list[str]:
    out: list[str] = []
    entries: list[Any] = as_list(raw) or []
    for entry in entries:
        text = " ".join(str(entry).split())[:ITEM_MAX_CHARS]
        if text and text.lower() not in {o.lower() for o in out}:
            out.append(text)
    return out[:MAX_ITEMS]


def _clip(value: object, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def _optional_text(value: object, limit: int) -> str | None:
    if isinstance(value, str) and value.strip() and value.strip().lower() != "null":
        return _clip(value, limit)
    return None


def _done_items(raw: object) -> list[dict[str, Any]]:
    """Normalize ``done_when``: plain strings and ``{text, check, status}`` objects are both accepted.

    ``status`` stays ``None`` when the advisor did not give a valid one; ``merge`` then inherits it from
    the matching earlier item (or ``open``).
    """
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    entries: list[Any] = as_list(raw) or []
    for entry in entries:
        obj = as_dict(entry)
        if obj is not None:
            text = _clip(obj.get("text") or obj.get("item") or "", DONE_MAX_CHARS)
            check = _optional_text(obj.get("check"), DONE_MAX_CHARS)
            raw_status = str(obj.get("status") or "").strip().lower()
            status = raw_status if raw_status in DONE_STATUSES else None
        else:
            text, check, status = _clip(entry, DONE_MAX_CHARS), None, None
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append({"text": text, "check": check, "status": status})
    return out[:DONE_MAX_ITEMS]


def _steps(raw: object) -> list[str]:
    entries: list[Any] = as_list(raw) or []
    out = [_clip(entry, ITEM_MAX_CHARS) for entry in entries]
    return [s for s in out if s][:STEP_MAX_ITEMS]


def parse_ledger(text: str) -> tuple[str, dict[str, Any] | None]:
    """Split an advisor reply into ``(guidance, ledger)``; ``ledger`` is None when absent/invalid.

    Template keys (``goal``, ``done_when``, ``steps``, ``unverified``) are present in the result only
    when the advisor gave a non-empty value, so ``merge`` can tell "not mentioned" from "replaced".
    """
    stripped = text.rstrip()
    match = _BLOCK_RE.search(stripped)
    if match is None:
        return text, None
    try:
        data = as_dict(json.loads(match.group(1)))
    except ValueError:
        return text, None
    if data is None or not (set(data) & {"verdict", *LIST_KEYS, *TEMPLATE_KEYS}):
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
    goal = _optional_text(data.get("goal"), GOAL_MAX_CHARS)
    if goal:
        ledger["goal"] = goal
    done = _done_items(data.get("done_when"))
    if done:
        ledger["done_when"] = done
    steps = _steps(data.get("steps"))
    if steps:
        ledger["steps"] = steps
    unverified = _items(data.get("unverified"))
    if unverified:
        ledger["unverified"] = unverified
    return stripped[: match.start()].rstrip(), ledger


def item_id(text: str) -> str:
    return hashlib.sha1(" ".join(text.lower().split()).encode("utf-8")).hexdigest()[:6]


def merge(previous: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """New open items replace the old ones (absent = closed); standing lists accumulate.

    ``goal`` and ``done_when`` are the exception: a reply that does not mention them keeps the previous
    ones, and an item without an explicit status inherits the status of the same item from before.
    """
    merged = dict(new)
    for key in ("do_not", "pitfalls"):
        seen: dict[str, str] = {}
        old: list[Any] = (previous or {}).get(key) or []
        added: list[Any] = new.get(key) or []
        for text in [*old, *added]:
            seen[str(text).lower()] = str(text)
        merged[key] = list(seen.values())[-MAX_STANDING:]

    prev = previous or {}
    if "goal" not in merged and prev.get("goal"):
        merged["goal"] = prev["goal"]
    prev_done: list[Any] = prev.get("done_when") or []
    if "done_when" not in merged:
        if prev_done:
            merged["done_when"] = list(prev_done)
    else:
        known: dict[str, Any] = {}
        for earlier in prev_done:
            obj = as_dict(earlier)
            if obj is not None:
                known[str(obj.get("text", "")).lower()] = obj.get("status")
        current: list[dict[str, Any]] = merged["done_when"]
        merged["done_when"] = [
            {**d, "status": d.get("status") or known.get(str(d["text"]).lower()) or "open"} for d in current
        ]
    return merged


def unmet_done(ledger: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Definition-of-done items not yet ``met`` (``unknown`` counts as unmet: it cannot be called done)."""
    if not ledger:
        return []
    items: list[Any] = ledger.get("done_when") or []
    unmet: list[dict[str, Any]] = []
    for item in items:
        obj = as_dict(item)
        if obj is not None and obj.get("status") != "met":
            unmet.append(obj)
    return unmet


def open_count(ledger: dict[str, Any] | None, *, include_done_when: bool = False) -> int:
    """Items the executor still has to act on (``must_fix`` + ``verify``, optionally unmet ``done_when``)."""
    if not ledger:
        return 0
    count = len(ledger.get("must_fix") or []) + len(ledger.get("verify") or [])
    if include_done_when:
        count += len(unmet_done(ledger))
    return count


def shape(ledger: dict[str, Any] | None) -> dict[str, int]:
    """How complete one parsed reply was, for logs and the exchange history (no schema to migrate)."""
    ledger = ledger or {}
    return {
        "parsed": int(bool(ledger)),
        "goal": int(bool(ledger.get("goal"))),
        "done_when": len(ledger.get("done_when") or []),
        "steps": len(ledger.get("steps") or []),
        "unverified": len(ledger.get("unverified") or []),
    }


def has_content(ledger: dict[str, Any] | None) -> bool:
    return bool(ledger) and (
        open_count(ledger) > 0
        or bool(ledger.get("do_not"))
        or bool(ledger.get("pitfalls"))
        or bool(ledger.get("goal"))
        or bool(ledger.get("done_when"))
        or ledger.get("verdict") in ("revise", "stop")
    )


_LABELS = {
    "must_fix": "Must fix",
    "verify": "Verify",
    "do_not": "Do not",
    "pitfalls": "Pitfalls",
    "unverified": "Unverified",
}
_DONE_MARK = {"met": "x", "unknown": "?"}


def render(
    ledger: dict[str, Any] | None,
    *,
    ids: bool = True,
    steps: bool = False,
    unmet_done_only: bool = False,
) -> str:
    """Plain-text ledger for the advisor prompt and the pinned executor section.

    ``steps`` is off by default (a plan goes stale quickly, so it is never pinned);
    ``unmet_done_only`` drops finished definition-of-done items from the pinned section.
    A ledger without template keys renders exactly as it did before they existed.
    """
    if not ledger:
        return ""
    lines = [f"Verdict: {ledger.get('verdict') or 'proceed'}"]

    def _list(key: str) -> None:
        values: list[Any] = ledger.get(key) or []
        entries = [str(t) for t in values]
        if not entries:
            return
        lines.append(f"{_LABELS[key]}:")
        lines.extend(f"- [{item_id(t)}] {t}" if ids else f"- {t}" for t in entries)

    if ledger.get("goal"):
        lines.append(f"Goal: {ledger['goal']}")
    _list("must_fix")
    _list("verify")
    done: list[Any] = ledger.get("done_when") or []
    done = [d for d in done if isinstance(d, dict)]
    if unmet_done_only:
        done = [d for d in done if d.get("status") != "met"]
    if done:
        lines.append("Definition of done:")
        for d in done:
            mark = _DONE_MARK.get(str(d.get("status")), " ")
            check = f" (check: {d['check']})" if d.get("check") else ""
            lines.append(f"- [{mark}] {d.get('text', '')}{check}")
    if steps and ledger.get("steps"):
        lines.append("Steps:")
        lines.extend(f"{n}. {s}" for n, s in enumerate(ledger["steps"], 1))
    _list("do_not")
    _list("pitfalls")
    _list("unverified")
    if ledger.get("next_checkpoint"):
        lines.append(f"Next checkpoint: {ledger['next_checkpoint']}")
    return "\n".join(lines)
