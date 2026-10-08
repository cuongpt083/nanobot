"""Advisor review-nudge policy.

Pure functions over the transcript, so the timing rules that decide when the
executor is prodded to consult the advisor are testable without the runner. The
thresholds and wording mirror AICoworker's in-run nudge (``attempt.ts``); the
tool classification is the one thing that had to change for nanobot's tool set.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any, Literal

from nanobot.coworker.advisor import ledger as advisor_ledger
from nanobot.coworker.advisor.consult import NON_EVIDENCE_TOOLS, current_run
from nanobot.coworker.advisor.evidence import WRITE_TOOLS, tool_call_paths
from nanobot.coworker.advisor.tool import ADVISOR_TOOL
from nanobot.coworker.config import AdvisorConfig
from nanobot.coworker.transcript import (
    as_dict,
    content_text,
    tool_call_arguments,
    tool_call_name,
    tool_calls,
)

ADVISOR_REVIEW_MARKER = "[auto-advisor-review]"
KIND_ADVISOR_REVIEW = "advisor_review"

# Reading and survey tools gather evidence but change nothing, so they are not a
# substitute for the review a real write deserves.
READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "read_file", "list_dir", "find_files", "rg", "grep", "web_search", "web_fetch",
    "list_sessions", "read_session", "search_sessions", "list_exec_sessions",
})

NudgeKind = Literal["first", "reconsult", "coding_result", "discussion", "done_gate", "room_review"]


@dataclass(frozen=True)
class RunScan:
    consulted: bool
    gap: int
    work_total: int
    files: frozenset[str] = frozenset()  # distinct files written since the last consult
    written_total: int = 0  # write-tool calls in the run (any consult)


@dataclass(frozen=True)
class NudgeDecision:
    kind: NudgeKind
    gap: int


def is_work_tool(name: str) -> bool:
    return bool(name) and name not in NON_EVIDENCE_TOOLS and name not in READ_ONLY_TOOLS


def scan_run(messages: list[dict[str, Any]]) -> RunScan:
    """Count the work steps since the last advisor consult in the current run."""
    consulted = False
    gap = 0
    work_total = 0
    written_total = 0
    files: set[str] = set()
    for message in current_run(messages):
        for call in tool_calls(message):
            name = tool_call_name(call)
            if name == ADVISOR_TOOL:
                consulted = True
                gap = 0
                files.clear()
            elif is_work_tool(name):
                gap += 1
                work_total += 1
                if name in WRITE_TOOLS:
                    written_total += 1
                    files.update(tool_call_paths(call))
    return RunScan(
        consulted=consulted,
        gap=gap,
        work_total=work_total,
        files=frozenset(files),
        written_total=written_total,
    )


def consult_after_last_write(messages: list[dict[str, Any]]) -> bool | None:
    """Whether a *successful* consult happened after the run's last file write.

    ``None`` when the run wrote nothing (there is nothing to review).
    """
    last_write = -1
    last_good_consult = -1
    for index, message in enumerate(current_run(messages)):
        if message.get("role") == "tool" and message.get("name") == ADVISOR_TOOL:
            if content_text(message.get("content")).lstrip().startswith("ADVISOR ("):
                last_good_consult = index
            continue
        if any(tool_call_name(c) in WRITE_TOOLS for c in tool_calls(message)):
            last_write = index
    if last_write < 0:
        return None
    return last_good_consult > last_write


@dataclass(frozen=True)
class EffectivePolicy:
    first_gap: int
    reconsult_gap: int
    checkpoint_files: int
    commit_gate: bool


def resolve_policy(
    cfg: AdvisorConfig, model: str | None, *, steps_override: int | None = None
) -> EffectivePolicy:
    """Global timing, then the first matching ``executor_profiles`` glob, then the advisor's own
    ``after_steps`` checkpoint (the party that knows the risk of the next step wins)."""
    first, reconsult = cfg.first_consult_gap, cfg.reconsult_gap
    files, gate = cfg.checkpoint_files, cfg.commit_gate
    for pattern, profile in cfg.executor_profiles.items():
        if model and fnmatch.fnmatch(model.lower(), pattern.lower()):
            first = profile.first_consult_gap or first
            reconsult = profile.reconsult_gap or reconsult
            files = profile.checkpoint_files or files
            gate = cfg.commit_gate if profile.commit_gate is None else profile.commit_gate
            break
    if steps_override:
        reconsult = steps_override
    return EffectivePolicy(first, reconsult, files, gate)


_IRREVERSIBLE_RE = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?(?:commit|push|reset\s+--hard|clean\s+-\w*f)\b"
    r"|\brm\s+(?:-\w+\s+)*-\w*(?:rf|fr)\w*\b"
    r"|\brm\s+-\w*r\w*\s+-\w*f\w*\b"
    r"|\bRemove-Item\b.*-Recurse.*-Force|\bRemove-Item\b.*-Force.*-Recurse",
    re.IGNORECASE,
)


def is_irreversible_call(tool: str, arguments: Any) -> bool:
    """A call the commit gate guards: ``git commit/push/reset --hard/clean -f``, ``rm -rf`` and friends."""
    if tool in ("git_commit", "git_push"):
        return True
    if tool not in ("exec", "exec_session"):
        return False
    typed = as_dict(arguments)
    if typed is not None:
        command = str(typed.get("command") or typed.get("cmd") or "")
    else:
        command = tool_call_arguments({"arguments": arguments})
    return _IRREVERSIBLE_RE.search(command) is not None


def done_gate_applies(ledger: dict[str, Any] | None) -> bool:
    """The executor is about to stop while the advisor still has open ``must_fix``/``verify`` items."""
    return advisor_ledger.open_count(ledger) > 0


def decide_review_nudge(
    scan: RunScan, *, first_gap: int, reconsult_gap: int, coding_result: bool
) -> NudgeDecision | None:
    if coding_result:
        # A finished coding task: a review is due unless the executor already asked.
        return None if scan.consulted else NudgeDecision("coding_result", scan.gap)
    threshold = reconsult_gap if scan.consulted else first_gap
    if scan.gap < threshold:
        return None
    return NudgeDecision("reconsult" if scan.consulted else "first", scan.gap)


def decide_discussion_gate(
    scan: RunScan,
    *,
    draft_chars: int,
    mode: str,
    gate: Literal["off", "brainstorm", "always"],
    min_chars: int,
    first_gap: int,
) -> NudgeDecision | None:
    """Decide whether an open-ended conversational reply must pass through the advisor."""
    if gate == "off":
        return None
    if gate == "brainstorm" and mode != "brainstorm":
        return None
    if scan.consulted:
        return None
    if scan.work_total >= first_gap:
        return None
    if draft_chars < min_chars:
        return None
    return NudgeDecision("discussion", gap=0)


def review_nudge_text(decision: NudgeDecision) -> str:
    """The injected text; always starts with ``ADVISOR_REVIEW_MARKER``."""
    if decision.kind == "coding_result":
        return (
            f"{ADVISOR_REVIEW_MARKER} A coding task finished and you have not consulted the advisor on it. "
            "Read the real changes first (coding_agent action=\"diff\" with the task id), then call "
            "advisor(focus=\"review this diff and the acceptance result before I recommend a merge\"). "
            "If it flags a real problem, steer or resume the task; otherwise report to the user."
        )
    if decision.kind == "done_gate":
        raise ValueError("done_gate text needs the ledger: use done_gate_text()")
    if decision.kind == "room_review":
        # The teammates' results are already in this turn; the advisor sees them in the transcript.
        return (
            f"{ADVISOR_REVIEW_MARKER} Your teammates have finished and their results are in the review "
            "above. Before you post the final consolidated report, call advisor(focus=<the user's goal, what "
            "each teammate delivered, and what you are unsure about>). It reviews the whole room transcript. "
            "Then fold any must-fix point into your report, and say plainly which teammate output you "
            "rejected or sent back. Do not skip the advisor call."
        )
    if decision.kind == "reconsult":
        return (
            f"{ADVISOR_REVIEW_MARKER} You have done a lot of work ({decision.gap} steps) since your last "
            "advisor consult. Call advisor() NOW for a fresh review — it sees everything you just did. "
            "If it flags a real problem, fix it before finishing; otherwise briefly confirm and continue. "
            "Do not skip the advisor call."
        )
    if decision.kind == "discussion":
        return (
            f"{ADVISOR_REVIEW_MARKER} Before this answer stands, call advisor(focus=<the user's core "
            "question, 1 sentence>) — it sees your draft above. Then add a SHORT follow-up (not a rewrite): "
            "where it agrees, where it differs, and your final position. If it changes nothing material, "
            "say so in one line."
        )
    return (
        f"{ADVISOR_REVIEW_MARKER} You did substantive work this run without consulting the advisor. "
        "Call advisor() NOW for a review — it sees your full transcript including everything you just did. "
        "If it flags a real problem, fix it before finishing; if not, briefly confirm completion. "
        "Do not skip the advisor call."
    )


def done_gate_text(ledger: dict[str, Any]) -> str:
    """Continuation when the executor tries to finish with advisor items still open."""
    return (
        f"{ADVISOR_REVIEW_MARKER} You are about to finish, but your advisor still has OPEN items "
        "from its earlier review:\n\n"
        f"{advisor_ledger.render(ledger)}\n\n"
        "For each Must fix / Verify item: do it now and show the evidence (tool output), or tell the user "
        "plainly that you are not doing it and why. Do not report the task as complete while an item is "
        "silently unaddressed. If you changed things, call advisor() once more so it can close the items."
    )
