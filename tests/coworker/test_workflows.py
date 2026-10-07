"""Workflow format/engine/drive/distill."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.coworker.workflows import drive
from nanobot.coworker.workflows.distill import distill
from nanobot.coworker.workflows.engine import (
    WorkflowEngineError,
    complete_step,
    make_emitter,
    start_run,
)
from nanobot.coworker.workflows.format import load_workflow, validate_workflow
from nanobot.coworker.workflows.registry import list_workflows

DECISION_SCHEMA = {
    "type": "object",
    "required": ["route", "reason"],
    "properties": {"route": {"enum": ["publish", "revise"]}, "reason": {"type": "string"}},
}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_review_workflow(root: Path) -> Path:
    wf = root / "workflows" / "review"
    _write(wf / "workflow.md", '---\nname: Review flow\ndescription: draft then review\nstart: "[[draft]]"\n---\n')
    _write(wf / "steps" / "draft.md", "---\ntype: task\n---\nWrite a draft.\n\n## Next\n- [[check]]\n")
    _write(
        wf / "steps" / "check.md",
        "---\ntype: decision\nmax_attempts: 3\n---\nIs it good?\n\n## Next\n"
        "- [[publish]] — when: good\n- [[draft]] — when: needs work\n\n"
        f"## Output\n```json\n{json.dumps({**DECISION_SCHEMA, 'properties': {'route': {'enum': ['publish', 'draft']}, 'reason': {'type': 'string'}}})}\n```\n",
    )
    _write(wf / "steps" / "publish.md", "---\ntype: end\n---\nPublish it.\n")
    return wf


def test_format_parses_edges_and_schema(tmp_path: Path) -> None:
    wf = load_workflow(make_review_workflow(tmp_path))
    assert wf.start == "draft"
    assert [e.to for e in wf.steps["check"].next] == ["publish", "draft"]
    assert wf.steps["check"].next[0].when == "good"
    assert wf.steps["check"].output_schema is not None
    assert validate_workflow(wf, strict=True).ok


def test_validation_reports_broken_graphs(tmp_path: Path) -> None:
    wf_dir = tmp_path / "bad"
    _write(wf_dir / "workflow.md", '---\nstart: "[[a]]"\n---\n')
    _write(wf_dir / "steps" / "a.md", "---\ntype: decision\n---\n## Next\n- [[missing]]\n")
    result = validate_workflow(load_workflow(wf_dir))
    assert not result.ok
    assert any("missing step [[missing]]" in e for e in result.errors)
    assert any("decision needs >= 2" in e for e in result.errors)


def test_engine_enforces_routing_and_schema(tmp_path: Path) -> None:
    wf = load_workflow(make_review_workflow(tmp_path))
    run, _ = start_run(wf, run_id="r1", run_input="topic")
    buf, emit = make_emitter(run)
    complete_step(wf, run, "draft", emit, output='{"text": "v1"}')
    assert run.active == ["check"]
    with pytest.raises(WorkflowEngineError) as bad_route:
        complete_step(wf, run, "check", emit, output='{"route": "nowhere", "reason": "x"}')
    assert bad_route.value.code == "schema_mismatch"
    with pytest.raises(WorkflowEngineError) as missing:
        complete_step(wf, run, "check", emit, output='{"route": "draft"}')
    assert missing.value.code == "schema_mismatch"
    complete_step(wf, run, "check", emit, output='{"route": "draft", "reason": "too short"}')
    assert run.active == ["draft"] and run.step_state["draft"].attempts == 2
    complete_step(wf, run, "draft", emit, output="{}")
    complete_step(wf, run, "check", emit, output='{"route": "publish", "reason": "good"}')
    complete_step(wf, run, "publish", emit)
    assert run.status == "done"
    assert any(e["ev"] == "route" for e in buf)


def test_parallel_join_waits_for_all_branches(tmp_path: Path) -> None:
    wf_dir = tmp_path / "par"
    _write(wf_dir / "workflow.md", '---\nstart: "[[fan]]"\n---\n')
    _write(wf_dir / "steps" / "fan.md", "---\ntype: parallel\n---\n## Next\n- [[a]]\n- [[b]]\n")
    _write(wf_dir / "steps" / "a.md", "A\n## Next\n- [[merge]]\n")
    _write(wf_dir / "steps" / "b.md", "B\n## Next\n- [[merge]]\n")
    _write(wf_dir / "steps" / "merge.md", "---\ntype: join\n---\n## Next\n- [[end]]\n")
    _write(wf_dir / "steps" / "end.md", "---\ntype: end\n---\n")
    wf = load_workflow(wf_dir)
    run, _ = start_run(wf, run_id="p", run_input=None)
    _, emit = make_emitter(run)
    complete_step(wf, run, "fan", emit)
    assert sorted(run.active) == ["a", "b"]
    complete_step(wf, run, "a", emit)
    assert run.step_state["merge"].status == "waiting"
    with pytest.raises(WorkflowEngineError) as waiting:
        complete_step(wf, run, "merge", emit)
    assert waiting.value.code == "join_waiting"
    complete_step(wf, run, "b", emit)
    assert run.step_state["merge"].status == "focus"


def test_drive_injects_steps_and_advances_on_valid_output(env) -> None:
    make_review_workflow(env.workspace)
    session = env.sessions.get_or_create("cli:direct")
    drive.start(session, env.workspace, "review", "write a post")

    injection, note = drive.on_turn_end(session, env.workspace, final_content="started",
                                        step_turn=None, genuine_user_text="run review")
    assert note is None and injection is not None and injection.step == "draft"
    assert injection.content.startswith("[auto-workflow:review:draft]")
    # A duplicate turn end (e.g. the user chats meanwhile) must not double-inject.
    assert drive.on_turn_end(session, env.workspace, final_content="hi", step_turn=None,
                             genuine_user_text="hello") == (None, None)

    step_turn = (injection.run_id, "draft")
    nxt, _ = drive.on_turn_end(session, env.workspace, final_content='Done.\n```json\n{"text": "v1"}\n```',
                               step_turn=step_turn, genuine_user_text=None)
    assert nxt is not None and nxt.step == "check"

    retry, _ = drive.on_turn_end(session, env.workspace, final_content="looks good",
                                 step_turn=(nxt.run_id, "check"), genuine_user_text=None)
    assert retry is not None and retry.step == "check"
    assert "REJECTED" in retry.content

    end, _ = drive.on_turn_end(session, env.workspace,
                               final_content='```json\n{"route": "publish", "reason": "solid"}\n```',
                               step_turn=(nxt.run_id, "check"), genuine_user_text=None)
    assert end is not None and end.step == "publish"
    done, note = drive.on_turn_end(session, env.workspace, final_content="Published.",
                                   step_turn=(nxt.run_id, "publish"), genuine_user_text=None)
    assert done is None and note is not None and note.startswith("✅")
    assert drive.binding(session) is None


def test_drive_pauses_on_unanswered_human_step(env) -> None:
    wf_dir = env.workspace / "workflows" / "ask"
    _write(wf_dir / "workflow.md", '---\nstart: "[[q]]"\n---\n')
    _write(wf_dir / "steps" / "q.md", "---\ntype: human\n---\nAsk the budget.\n## Next\n- [[end]]\n")
    _write(wf_dir / "steps" / "end.md", "---\ntype: end\n---\n")
    session = env.sessions.get_or_create("cli:direct")
    drive.start(session, env.workspace, "ask", "")
    first, _ = drive.on_turn_end(session, env.workspace, final_content="", step_turn=None, genuine_user_text=None)
    assert first is not None
    paused, _ = drive.on_turn_end(session, env.workspace, final_content="What is the budget?",
                                  step_turn=(first.run_id, "q"), genuine_user_text=None)
    assert paused is None and drive.binding(session)["human_wait"] == "q"
    again, _ = drive.on_turn_end(session, env.workspace, final_content="Thanks!", step_turn=None,
                                 genuine_user_text="500 USD")
    assert again is not None and "The user has replied" in again.content


def test_distill_writes_a_valid_linear_draft(env) -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Fetch the sales report"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "web_fetch", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "1", "name": "web_fetch", "content": "data"},
        {"role": "assistant", "content": "Fetched."},
        {"role": "user", "content": "Summarize it into a table"},
        {"role": "assistant", "content": "Here is the table."},
        {"role": "user", "content": "[auto-advisor-review] call advisor"},
        {"role": "user", "content": "save this as a workflow"},
    ]
    result = distill(env.workspace, "sales", messages)
    assert result.phases == 2 and result.steps == 3
    assert result.validation.ok
    assert [w.ref for w in list_workflows(env.workspace)] == ["sales-draft"]
    first_step = (result.dir / "steps" / "01-fetch-the-sales-report.md").read_text(encoding="utf-8")
    assert "web_fetch ×1" in first_step


def test_extract_last_json_handles_untagged_and_embedded_blocks() -> None:
    assert drive.extract_last_json('x ```json\n{"a":1}\n``` y ```json\n{"a":2}\n```') == '{"a":2}'
    assert drive.extract_last_json('```\n{"a": 3}\n```') == '{"a": 3}'
    assert drive.extract_last_json('Result: {"a": {"b": 4}} done') == '{"a": {"b": 4}}'
    assert drive.extract_last_json("no json") is None
