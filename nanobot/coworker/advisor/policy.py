"""Advisor review-nudge policy.

Pure functions over the transcript, so the timing rules that decide when the
executor is prodded to consult the advisor are testable without the runner. The
thresholds and wording mirror AICoworker's in-run nudge (``attempt.ts``); the
tool classification is the one thing that had to change for nanobot's tool set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from nanobot.coworker.advisor.consult import NON_EVIDENCE_TOOLS, current_run
from nanobot.coworker.advisor.tool import ADVISOR_TOOL
from nanobot.coworker.transcript import tool_call_name, tool_calls

ADVISOR_REVIEW_MARKER = "[auto-advisor-review]"
KIND_ADVISOR_REVIEW = "advisor_review"

# Reading and survey tools gather evidence but change nothing, so they are not a
# substitute for the review a real write deserves.
READ_ONLY_TOOLS: frozenset[str] = frozenset({
    "read_file", "list_dir", "find_files", "rg", "grep", "web_search", "web_fetch",
    "list_sessions", "read_session", "search_sessions", "list_exec_sessions",
})

NudgeKind = Literal["first", "reconsult", "coding_result", "discussion"]


@dataclass(frozen=True)
class RunScan:
    consulted: bool
    gap: int
    work_total: int


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
    for message in current_run(messages):
        for call in tool_calls(message):
            name = tool_call_name(call)
            if name == ADVISOR_TOOL:
                consulted = True
                gap = 0
            elif is_work_tool(name):
                gap += 1
                work_total += 1
    return RunScan(consulted=consulted, gap=gap, work_total=work_total)


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
