"""The advisor's own ``next_checkpoint``: when it asked to be consulted again."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from nanobot.coworker.advisor.evidence import EXEC_TOOLS, WRITE_TOOLS, matches_any

Kind = Literal["before_write", "after_exec", "after_steps"]
_FORMS = ("before_write", "after_exec", "after_steps")


@dataclass(frozen=True)
class Checkpoint:
    kind: Kind
    arg: str  # glob / regex / step count as text

    @property
    def steps(self) -> int | None:
        return int(self.arg) if self.kind == "after_steps" else None


def parse_checkpoint(raw: object) -> Checkpoint | None:
    """``before_write:<glob>`` | ``after_exec:<regex>`` | ``after_steps:<n>``; anything else is None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().strip("`").strip()
    kind, sep, arg = text.partition(":")
    kind, arg = kind.strip().lower(), arg.strip().strip("`").strip()
    if not sep or kind not in _FORMS or not arg:
        return None
    if kind == "after_steps":
        if not arg.isdigit() or not 2 <= int(arg) <= 200:
            return None
    elif kind == "after_exec":
        try:
            re.compile(arg)
        except re.error:
            return None
    return Checkpoint(kind, arg)  # type: ignore[arg-type]


def hits(
    checkpoint: Checkpoint | None,
    *,
    tool: str,
    paths: list[str],
    command: str,
) -> bool:
    """Whether this just-executed tool call is the situation the advisor asked to be told about."""
    if checkpoint is None:
        return False
    if checkpoint.kind == "before_write":
        return tool in WRITE_TOOLS and any(matches_any(p, [checkpoint.arg]) for p in paths)
    if checkpoint.kind == "after_exec":
        return tool in EXEC_TOOLS and re.search(checkpoint.arg, command) is not None
    return False  # after_steps adjusts the step gap instead of firing on a call
