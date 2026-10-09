"""Per-session advisor enablement, model choice and consult budget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nanobot.coworker.advisor import ledger as advisor_ledger
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.runtime import session_state
from nanobot.coworker.transcript import as_dict, as_list

OFF = "off"
MODE_CODING = "coding"
MODE_BRAINSTORM = "brainstorm"
MODES = (MODE_CODING, MODE_BRAINSTORM)
HISTORY_LIMIT = 6
NOTES_LIMIT = 60
LOW_BUDGET_WARNING = 2
ADVICE_MAX_CHARS = 6000


@dataclass(frozen=True)
class AdvisorEffective:
    preset: str
    uses: int
    max_uses: int
    max_tokens: int
    early_refused: bool
    mode: str = MODE_CODING


def _slot(session: Any) -> dict[str, Any]:
    state = session_state(session)
    slot = as_dict(state.get("advisor"))
    if slot is None:
        slot = {}
        state["advisor"] = slot
    # /new keeps metadata but empties the transcript: the budget follows the transcript.
    size = len(session.messages)
    if size < int(slot.get("seen_len", 0) or 0):
        slot.pop("uses", None)
        slot.pop("early_refused", None)
        slot.pop("history", None)
        slot.pop("user_request", None)
        slot.pop("stuck_ids", None)
        for key in ("ledger", "notes", "work_steps", "checkpoint_fired", "last_gate"):
            slot.pop(key, None)
    slot["seen_len"] = size
    return slot


def effective(session: Any) -> AdvisorEffective | None:
    """None when the advisor is disabled for this session."""
    cfg = load_coworker_config().advisor
    slot = _slot(session)
    override = slot.get("preset")
    preset = override if isinstance(override, str) and override.strip() else cfg.preset
    if not preset or preset == OFF:
        return None
    # D1: the budget regrows with real work, so a long session is not locked out after a fixed count.
    earned = int(slot.get("work_steps", 0) or 0) // cfg.refill_steps if cfg.refill_steps else 0
    return AdvisorEffective(
        preset=preset,
        uses=int(slot.get("uses", 0) or 0),
        max_uses=int(slot.get("max_uses") or cfg.max_uses) + earned,
        max_tokens=cfg.max_tokens,
        early_refused=slot.get("early_refused") is True,
        mode=mode_of(slot),
    )


def mode_of(slot: dict[str, Any]) -> str:
    return MODE_BRAINSTORM if slot.get("mode") == MODE_BRAINSTORM else MODE_CODING


def set_preset(session: Any, preset: str | None) -> None:
    """``None`` inherits the global default; ``"off"`` disables."""
    slot = _slot(session)
    if preset is None:
        slot.pop("preset", None)
    else:
        slot["preset"] = preset


def apply_switch(
    session: Any,
    *,
    enabled: bool | None = None,
    preset: str | None = None,
    mode: str | None = None,
) -> AdvisorEffective | None:
    """Manual per-session switch. Turning on needs a preset: the given one, the session's, or the global."""
    if mode is not None:
        if mode not in MODES:
            raise ValueError(f"unknown advisor mode {mode!r}")
        set_mode(session, mode)
    if enabled is False:
        set_preset(session, OFF)
    elif enabled is True or preset:
        if preset:
            if preset == OFF:
                raise ValueError("preset 'off' cannot be selected while enabling the advisor")
            set_preset(session, preset)
        elif _slot(session).get("preset") in (None, OFF):
            set_preset(session, None)  # fall back to the global default preset
        if effective(session) is None:
            raise ValueError("no advisor preset configured: choose a model preset")
    return effective(session)


def set_mode(session: Any, mode: str) -> None:
    _slot(session)["mode"] = MODE_BRAINSTORM if mode == MODE_BRAINSTORM else MODE_CODING


def current_mode(session: Any) -> str:
    return mode_of(_slot(session))


def count_use(session: Any) -> int:
    slot = _slot(session)
    slot["uses"] = int(slot.get("uses", 0) or 0) + 1
    return slot["uses"]


def reset_uses(session: Any) -> None:
    """Reset the advisor consult budget count for this session."""
    slot = _slot(session)
    slot["uses"] = 0


def mark_early_refusal(session: Any) -> None:
    _slot(session)["early_refused"] = True


def mark_user_request(session: Any) -> None:
    """The user explicitly asked for the advisor this turn: skip the thin-context refusal."""
    _slot(session)["user_request"] = True


def clear_user_request(session: Any) -> None:
    _slot(session).pop("user_request", None)


def user_requested(session: Any) -> bool:
    return _slot(session).get("user_request") is True


FOCUS_MAX_CHARS = 200


def record_consult(
    session: Any,
    *,
    model: str,
    focus: str | None,
    duration_ms: int,
    ok: bool,
    now: float,
) -> None:
    """Remember the latest real consult attempt (refusals for thin context are not recorded)."""
    _slot(session)["last_consult"] = {
        "at": now,
        "model": model,
        "focus": (focus or "")[:FOCUS_MAX_CHARS] or None,
        "duration_ms": duration_ms,
        "ok": ok,
    }


def record_exchange(
    session: Any,
    *,
    model: str,
    focus: str | None,
    advice: str,
    mode: str,
    now: float,
    shape: dict[str, int] | None = None,
) -> None:
    """Keep the latest question/answer pairs so the WebUI can show what the executor asked."""
    slot = _slot(session)
    history: list[Any] = as_list(slot.get("history")) or []
    entry: dict[str, Any] = {
        "at": now,
        "model": model,
        "mode": mode,
        "focus": (focus or "")[:FOCUS_MAX_CHARS] or None,
        "advice": advice[:ADVICE_MAX_CHARS],
        "n": int(slot.get("uses", 0) or 0),
    }
    if shape is not None:
        entry["shape"] = shape
    history.append(entry)
    slot["history"] = history[-HISTORY_LIMIT:]


def history(session: Any) -> list[dict[str, Any]]:
    raw: list[Any] = as_list(_slot(session).get("history")) or []
    return [d for d in (as_dict(x) for x in raw) if d is not None]


def record_review_nudge(session: Any, *, kind: str, now: float) -> None:
    """Remember that the harness just prodded the executor to consult (drives the UI chip)."""
    _slot(session)["review_nudge"] = {"at": now, "kind": kind}


def review_nudge(session: Any) -> dict[str, Any] | None:
    return as_dict(_slot(session).get("review_nudge"))


def last_consult(session: Any) -> dict[str, Any] | None:
    return as_dict(_slot(session).get("last_consult"))


def add_stuck_id(session: Any, call_id: str) -> None:
    slot = _slot(session)
    raw = as_list(slot.get("stuck_ids")) or []
    ids = [str(x) for x in raw]
    if call_id not in ids:
        ids.append(call_id)
    slot["stuck_ids"] = ids[-50:]


def stuck_ids(session: Any) -> frozenset[str]:
    raw = as_list(_slot(session).get("stuck_ids")) or []
    return frozenset(str(x) for x in raw)


# ---------- steering: ledger, per-result notes, work counter ----------


def ledger(session: Any) -> dict[str, Any] | None:
    return as_dict(_slot(session).get("ledger"))


def apply_ledger(session: Any, parsed: dict[str, Any]) -> dict[str, Any]:
    """Store a freshly parsed advisor ledger (open items replace, standing lists accumulate)."""
    slot = _slot(session)
    merged = advisor_ledger.merge(as_dict(slot.get("ledger")), parsed)
    merged["at"] = parsed.get("at", 0.0)
    slot["ledger"] = merged
    slot.pop("checkpoint_fired", None)  # a new consult re-arms the advisor's checkpoint
    return merged


def clear_ledger(session: Any) -> None:
    slot = _slot(session)
    slot.pop("ledger", None)
    slot.pop("checkpoint_fired", None)


def count_work_step(session: Any) -> int:
    slot = _slot(session)
    slot["work_steps"] = int(slot.get("work_steps", 0) or 0) + 1
    return slot["work_steps"]


def checkpoint_fired(session: Any) -> bool:
    return _slot(session).get("checkpoint_fired") is True


def mark_checkpoint_fired(session: Any) -> None:
    _slot(session)["checkpoint_fired"] = True


def add_result_note(session: Any, call_id: str, text: str) -> None:
    """Attach a stable note to one tool result; applied on every later request, byte-identical."""
    slot = _slot(session)
    notes = as_dict(slot.get("notes")) or {}
    notes.setdefault(call_id, text)
    if len(notes) > NOTES_LIMIT:
        for key in list(notes)[: len(notes) - NOTES_LIMIT]:
            notes.pop(key, None)
    slot["notes"] = notes


def result_notes(session: Any) -> dict[str, str]:
    raw = as_dict(_slot(session).get("notes")) or {}
    return {str(k): str(v) for k, v in raw.items()}
