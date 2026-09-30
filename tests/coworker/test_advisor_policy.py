"""Advisor nudge policy: work-step counting and the decision table."""

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.loader import ToolLoader
from nanobot.config.schema import Config
from nanobot.coworker.advisor import policy


def _run(*names: str) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": "build it"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": f"c{i}", "type": "function", "function": {"name": name}}
                for i, name in enumerate(names)
            ],
        },
    ]


def _scan(consulted: bool, gap: int) -> policy.RunScan:
    return policy.RunScan(consulted=consulted, gap=gap, work_total=gap)


# ---------- scan_run ----------

def test_scan_of_a_run_without_tools_is_empty() -> None:
    scan = policy.scan_run(_run())
    assert (scan.consulted, scan.gap, scan.work_total) == (False, 0, 0)


def test_scan_counts_writes_and_resets_the_gap_on_a_consult() -> None:
    scan = policy.scan_run(_run("write_file", "write_file", "advisor", "write_file", "write_file", "write_file"))
    assert scan.consulted is True
    assert scan.gap == 3  # only the writes after the consult
    assert scan.work_total == 5


def test_scan_ignores_read_only_tools() -> None:
    scan = policy.scan_run(_run("read_file", "list_dir", "find_files", "rg", "grep", "web_search"))
    assert (scan.consulted, scan.gap, scan.work_total) == (False, 0, 0)


def test_an_injected_review_marker_does_not_anchor_a_new_run() -> None:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "do work"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "write_file"}}]},
        {"role": "user", "content": f"{policy.ADVISOR_REVIEW_MARKER} call advisor"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "2", "function": {"name": "write_file"}}]},
    ]
    scan = policy.scan_run(messages)
    assert scan.work_total == 2 and scan.gap == 2


# ---------- decide_review_nudge ----------

def test_decide_uses_the_first_gap_until_a_consult() -> None:
    assert policy.decide_review_nudge(
        _scan(False, 1), first_gap=2, reconsult_gap=12, coding_result=False
    ) is None
    assert policy.decide_review_nudge(
        _scan(False, 2), first_gap=2, reconsult_gap=12, coding_result=False
    ) == policy.NudgeDecision("first", 2)


def test_decide_reconsults_on_a_long_run_after_a_consult() -> None:
    assert policy.decide_review_nudge(
        _scan(True, 11), first_gap=2, reconsult_gap=12, coding_result=False
    ) is None
    assert policy.decide_review_nudge(
        _scan(True, 12), first_gap=2, reconsult_gap=12, coding_result=False
    ) == policy.NudgeDecision("reconsult", 12)


def test_decide_coding_result_nudges_only_when_unreviewed() -> None:
    assert policy.decide_review_nudge(
        _scan(False, 0), first_gap=2, reconsult_gap=12, coding_result=True
    ) == policy.NudgeDecision("coding_result", 0)
    assert policy.decide_review_nudge(
        _scan(True, 5), first_gap=2, reconsult_gap=12, coding_result=True
    ) is None


# ---------- review_nudge_text ----------

def test_texts_always_start_with_the_marker() -> None:
    for kind, gap in (("first", 2), ("reconsult", 13), ("coding_result", 0), ("discussion", 0)):
        text = policy.review_nudge_text(policy.NudgeDecision(kind, gap))  # type: ignore[arg-type]
        assert text.startswith(policy.ADVISOR_REVIEW_MARKER)


def test_reconsult_text_reports_the_gap_and_forbids_skipping() -> None:
    text = policy.review_nudge_text(policy.NudgeDecision("reconsult", 13))
    assert "(13 steps)" in text and "Do not skip the advisor call." in text


def test_coding_result_text_points_at_the_diff() -> None:
    text = policy.review_nudge_text(policy.NudgeDecision("coding_result", 0))
    assert 'action="diff"' in text and "advisor(" in text


# ---------- guard against future tool renames ----------

def test_read_only_tool_names_are_real_builtin_tools(env) -> None:
    ctx = ToolContext(config=Config().tools, workspace=str(env.workspace), sessions=env.sessions)
    names: set[str] = set()
    for tool_cls in ToolLoader().discover():
        try:
            names.add(tool_cls.create(ctx).name)
        except Exception:
            continue
    missing = policy.READ_ONLY_TOOLS - names
    assert missing == set(), f"unknown read-only tool names: {sorted(missing)}"
