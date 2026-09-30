"""Per-session advisor enablement, model choice and consult budget."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.runtime import session_state
from nanobot.coworker.transcript import as_dict

OFF = "off"


@dataclass(frozen=True)
class AdvisorEffective:
    preset: str
    uses: int
    max_uses: int
    max_tokens: int
    early_refused: bool


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
    return AdvisorEffective(
        preset=preset,
        uses=int(slot.get("uses", 0) or 0),
        max_uses=int(slot.get("max_uses") or cfg.max_uses),
        max_tokens=cfg.max_tokens,
        early_refused=slot.get("early_refused") is True,
    )


def set_preset(session: Any, preset: str | None) -> None:
    """``None`` inherits the global default; ``"off"`` disables."""
    slot = _slot(session)
    if preset is None:
        slot.pop("preset", None)
    else:
        slot["preset"] = preset


def count_use(session: Any) -> int:
    slot = _slot(session)
    slot["uses"] = int(slot.get("uses", 0) or 0) + 1
    return slot["uses"]


def mark_early_refusal(session: Any) -> None:
    _slot(session)["early_refused"] = True
