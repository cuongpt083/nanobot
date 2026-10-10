"""Advisor steering: evidence pack, ledger, checkpoints, done-gate, commit gate, budget refill."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext, CompositeHook
from nanobot.agent.tools.base import ToolResult
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.coworker import metrics_store, runtime
from nanobot.coworker.advisor import checkpoint, evidence, policy
from nanobot.coworker.advisor import ledger as advisor_ledger
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import (
    ADVISOR_SYSTEM_PROMPT,
    LEDGER_INSTRUCTION,
    build_consult_prompt,
    run_consult,
)
from nanobot.coworker.advisor.tool import AdvisorTool
from nanobot.coworker.config import AdvisorConfig, CoworkerConfig, ExecutorProfile
from nanobot.coworker.hook import CoworkerHook
from nanobot.providers.base import LLMResponse, ToolCallRequest

KEY = "cli:direct"


def _call(call_id: str, name: str, **args: Any) -> dict[str, Any]:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _assistant(*calls: dict[str, Any]) -> dict[str, Any]:
    return {"role": "assistant", "content": "", "tool_calls": list(calls)}


def _tool(call_id: str, name: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.py").write_text("print('one')\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


# ---------- A1 / A2: evidence ----------

def test_written_paths_covers_all_write_tools_and_orders_by_recency() -> None:
    messages = [
        _assistant(_call("1", "write_file", path="a.py"), _call("2", "read_file", path="x.py")),
        _assistant(_call("3", "apply_patch", edits=[{"path": "b.py"}, {"path": "c.py"}])),
        _assistant(_call("4", "edit_file", path="a.py")),
    ]
    assert evidence.written_paths(messages) == ["b.py", "c.py", "a.py"]


def test_recent_checks_keep_exit_code_and_tail() -> None:
    long_out = "\n".join(f"line {i}" for i in range(100)) + "\nExit code: 1"
    messages = [
        _assistant(_call("1", "exec", command="pytest -q"), _call("2", "exec", command="ls")),
        _tool("1", "exec", long_out),
        _tool("2", "exec", "x\nExit code: 0"),
    ]
    checks = evidence.recent_checks(messages)
    assert len(checks) == 1  # `ls` is not a verification command
    command, tail, code = checks[0]
    assert command == "pytest -q" and code == 1
    assert "line 99" in tail and "line 10" not in tail


def test_evidence_contains_real_diff_untracked_file_and_checks(repo: Path) -> None:
    (repo / "a.py").write_text("print('two')\n", encoding="utf-8")
    (repo / "new.py").write_text("NEW_FILE_BODY = 1\n", encoding="utf-8")
    messages = [
        _assistant(_call("1", "write_file", path="a.py"), _call("2", "write_file", path="new.py")),
        _assistant(_call("3", "exec", command="ruff check .")),
        _tool("3", "exec", "All checks passed!\nExit code: 0"),
    ]
    text = evidence.collect_evidence_sync(messages, repo)
    assert "git status --short" in text and "M a.py" in text
    assert "-print('one')" in text and "+print('two')" in text
    assert "NEW_FILE_BODY" in text and "new/untracked" in text
    assert "`ruff check .` → exit code 0" in text


def test_evidence_is_empty_outside_git_and_without_checks(tmp_path: Path) -> None:
    assert evidence.collect_evidence_sync([], tmp_path) == ""


def test_files_written_outside_git_are_attached_so_the_advisor_sees_what_was_produced(tmp_path: Path) -> None:
    # A marketing or CRM workspace is not a git work tree: without this the advisor only has the first
    # 600 characters of each write call, and answers that it cannot see the document.
    (tmp_path / "offer.md").write_text("# OFFER BODY " + "x" * 3000, encoding="utf-8")
    messages = [_assistant(_call("1", "write_file", path="offer.md", content="# OFFER BODY"))]
    text = evidence.collect_evidence_sync(messages, tmp_path)
    assert "Files the executor wrote this run" in text
    assert "offer.md" in text and "OFFER BODY" in text and "new/untracked file" in text
    assert "git status --short" not in text


def test_a_write_outside_the_project_is_named_but_not_read(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (tmp_path / "elsewhere.md").write_text("OUTSIDE SECRET", encoding="utf-8")
    messages = [_assistant(_call("1", "write_file", path="../elsewhere.md"))]
    text = evidence.collect_evidence_sync(messages, root)
    assert "outside the project scope" in text and "OUTSIDE SECRET" not in text


def test_requested_files_are_read_from_disk_inside_the_project_only(repo: Path, tmp_path: Path) -> None:
    (repo / "plan.md").write_text("# PLAN BODY\n", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")
    text = evidence.read_requested_files(repo, ["plan.md", str(secret), "../secret.txt", "missing.md"])
    assert "# PLAN BODY" in text
    assert "TOP SECRET" not in text
    assert text.count("outside the project scope") == 2 and "missing, binary or unreadable" in text


def test_matches_any_matches_trailing_subpaths() -> None:
    assert evidence.matches_any("C:\\p\\webui\\src\\a.tsx", ["webui/src/**"])
    assert evidence.matches_any("nanobot/coworker/hook.py", ["coworker/*.py"])
    assert not evidence.matches_any("docs/x.md", ["webui/src/**"])


@pytest.mark.asyncio
async def test_consult_prompt_carries_evidence_ledger_and_instruction() -> None:
    messages = [{"role": "user", "content": "do it"}, _assistant(_call("1", "read_file", path="a")), _tool("1", "read_file", "x")]
    prompt, _ = build_consult_prompt(messages, "q", evidence="DIFF-BODY", ledger_text="- [abc123] fix X")
    assert "<harness_evidence>" in prompt and "DIFF-BODY" in prompt
    assert "Open advisor ledger" in prompt and "[abc123] fix X" in prompt
    assert "UNVERIFIED" in ADVISOR_SYSTEM_PROMPT and "harness_evidence" in ADVISOR_SYSTEM_PROMPT

    provider = SimpleNamespace(chat_with_retry=AsyncMock(return_value=LLMResponse(content="ok", finish_reason="stop")))
    rt = SimpleNamespace(provider=provider, model="m")
    res = await run_consult(messages=messages, runtime=rt, focus=None, max_tokens=64, timeout_s=5,
                            allow_thin=True, evidence="E", ledger=True)
    assert res.ok and res.evidence
    assert provider.chat_with_retry.await_args.kwargs["messages"][0]["content"].endswith(LEDGER_INSTRUCTION)


# ---------- B1: ledger ----------

ADVICE = """Fix the WebUI types first.

```json
{"verdict": "revise", "must_fix": ["CoworkerSettings.tsx still reads coding.agy", "  "],
 "verify": ["run bun run test"], "do_not": ["touch Pi"], "pitfalls": ["rg working_dir must be a dir"],
 "next_checkpoint": "after_exec:vitest|bun run test"}
```
"""


def test_parse_ledger_strips_block_and_normalizes() -> None:
    text, ledger = advisor_ledger.parse_ledger(ADVICE)
    assert text == "Fix the WebUI types first."
    assert ledger is not None
    assert ledger["verdict"] == "revise"
    assert ledger["must_fix"] == ["CoworkerSettings.tsx still reads coding.agy"]
    assert ledger["next_checkpoint"] == "after_exec:vitest|bun run test"
    assert advisor_ledger.open_count(ledger) == 2


@pytest.mark.parametrize("raw", [
    "plain advice, no block",
    "advice\n```json\n{not json}\n```",
    'advice\n```json\n{"unrelated": 1}\n```',
    'advice\n```json\n{"verdict": "proceed"}\n```\nand then more prose',
])
def test_parse_ledger_is_forgiving(raw: str) -> None:
    text, ledger = advisor_ledger.parse_ledger(raw)
    assert ledger is None and text == raw


def test_merge_closes_absent_items_and_accumulates_standing_lists() -> None:
    first = {"verdict": "revise", "must_fix": ["a", "b"], "verify": [], "do_not": ["x"], "pitfalls": ["p1"], "next_checkpoint": None}
    second = {"verdict": "proceed", "must_fix": ["b"], "verify": ["v"], "do_not": [], "pitfalls": ["p2", "p1"], "next_checkpoint": None}
    merged = advisor_ledger.merge(first, second)
    assert merged["must_fix"] == ["b"] and merged["verify"] == ["v"]
    assert merged["do_not"] == ["x"] and merged["pitfalls"] == ["p1", "p2"]
    assert advisor_ledger.has_content(merged)
    assert not advisor_ledger.has_content({"verdict": "proceed", "must_fix": [], "verify": [], "do_not": [], "pitfalls": []})


@pytest.mark.asyncio
async def test_tool_stores_ledger_hides_block_and_records_metrics(env, monkeypatch, repo) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", max_uses=3, refill_steps=0)))
    provider = SimpleNamespace(chat_with_retry=AsyncMock(return_value=LLMResponse(content=ADVICE, finish_reason="stop")))
    monkeypatch.setattr("nanobot.coworker.advisor.tool.runtime_for_preset", lambda p: SimpleNamespace(provider=provider, model="strong"))
    monkeypatch.setattr("nanobot.coworker.advisor.tool.project_root_for", lambda session: repo)
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(metrics_store, "record_advisor_consult", lambda **kw: recorded.append(kw))
    session = env.sessions.get_or_create(KEY)
    messages = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "go"},
        _assistant(_call("1", "write_file", path="a.py")),
        _tool("1", "write_file", "ok"),
    ]
    runtime.remember_live_messages(KEY, messages)
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key=KEY)):
        out = await AdvisorTool().execute(focus="check", files=["a.py"])
    text = str(out)
    assert "```json" not in text and "Fix the WebUI types first." in text
    assert "Advisor checkpoint: after_exec:vitest|bun run test" in text
    sent = provider.chat_with_retry.await_args.kwargs["messages"]
    assert "<harness_evidence>" in sent[1]["content"] and "print('one')" in sent[1]["content"]
    assert sent[0]["content"].endswith(LEDGER_INSTRUCTION)
    ledger = advisor_state.ledger(session)
    assert ledger is not None and ledger["verdict"] == "revise"
    assert advisor_state.history(session)[-1]["advice"] == "Fix the WebUI types first."
    assert recorded and recorded[0]["verdict"] == "revise" and recorded[0]["after_write"] is True
    assert recorded[0]["evidence_pack"] is True and recorded[0]["checkpoint_set"] is True


@pytest.mark.asyncio
async def test_tool_skips_ledger_when_disabled(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", ledger=False, evidence_pack=False)))
    provider = SimpleNamespace(chat_with_retry=AsyncMock(return_value=LLMResponse(content=ADVICE, finish_reason="stop")))
    monkeypatch.setattr("nanobot.coworker.advisor.tool.runtime_for_preset", lambda p: SimpleNamespace(provider=provider, model="strong"))
    session = env.sessions.get_or_create(KEY)
    runtime.remember_live_messages(KEY, [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}])
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key=KEY)):
        await AdvisorTool().execute(focus="x" * 50)
        out = await AdvisorTool().execute(focus="x")
    assert "```json" in str(out)  # untouched
    assert advisor_state.ledger(session) is None
    sent = provider.chat_with_retry.await_args.kwargs["messages"]
    assert not sent[0]["content"].endswith(LEDGER_INSTRUCTION) and "<harness_evidence>" not in sent[1]["content"]


# ---------- B4: checkpoints ----------

def test_parse_checkpoint_forms() -> None:
    assert checkpoint.parse_checkpoint("before_write:webui/src/**") == checkpoint.Checkpoint("before_write", "webui/src/**")
    assert checkpoint.parse_checkpoint("`after_exec:pytest|vitest`").kind == "after_exec"
    assert checkpoint.parse_checkpoint("after_steps:6").steps == 6
    for bad in ("after_steps:1", "after_steps:x", "after_exec:(", "sometime later", "", None, "before_write:"):
        assert checkpoint.parse_checkpoint(bad) is None


def test_checkpoint_hits() -> None:
    write = checkpoint.parse_checkpoint("before_write:webui/src/**")
    assert checkpoint.hits(write, tool="write_file", paths=["C:\\p\\webui\\src\\a.tsx"], command="")
    assert not checkpoint.hits(write, tool="read_file", paths=["webui/src/a.tsx"], command="")
    run = checkpoint.parse_checkpoint("after_exec:pytest")
    assert checkpoint.hits(run, tool="exec", paths=[], command="uv run pytest -q")
    assert not checkpoint.hits(run, tool="exec", paths=[], command="ls")
    assert not checkpoint.hits(checkpoint.parse_checkpoint("after_steps:5"), tool="exec", paths=[], command="x")


# ---------- policy ----------

def test_scan_tracks_files_and_writes_since_the_last_consult() -> None:
    messages = [
        {"role": "user", "content": "build"},
        _assistant(_call("1", "write_file", path="a.py"), _call("2", "write_file", path="b.py")),
        _assistant(_call("3", "advisor")),
        _assistant(_call("4", "edit_file", path="c.py"), _call("5", "read_file", path="z")),
    ]
    scan = policy.scan_run(messages)
    assert scan.files == frozenset({"c.py"}) and scan.gap == 1 and scan.written_total == 3


def test_consult_after_last_write_needs_a_successful_consult() -> None:
    base = [{"role": "user", "content": "go"}, _assistant(_call("1", "write_file", path="a"))]
    assert policy.consult_after_last_write([{"role": "user", "content": "go"}]) is None
    assert policy.consult_after_last_write(base) is False
    refused = [*base, _assistant(_call("2", "advisor")), _tool("2", "advisor", '{"status": "insufficient_context"}')]
    assert policy.consult_after_last_write(refused) is False
    good = [*base, _assistant(_call("2", "advisor")), _tool("2", "advisor", "ADVISOR (m) — advice 1/10:\n\nok")]
    assert policy.consult_after_last_write(good) is True
    rewritten = [*good, _assistant(_call("3", "edit_file", path="a"))]
    assert policy.consult_after_last_write(rewritten) is False


def test_resolve_policy_profile_then_advisor_steps() -> None:
    cfg = AdvisorConfig(
        reconsult_gap=12,
        commit_gate=True,
        executor_profiles={"*flash*": ExecutorProfile(reconsult_gap=6, commit_gate=False, checkpoint_files=3)},
    )
    base = policy.resolve_policy(cfg, "claude-opus-5-5")
    assert (base.reconsult_gap, base.commit_gate, base.checkpoint_files) == (12, True, 5)
    weak = policy.resolve_policy(cfg, "google-antigravity/Gemini-3.8-FLASH-tiered")
    assert (weak.reconsult_gap, weak.commit_gate, weak.checkpoint_files) == (6, False, 3)
    assert policy.resolve_policy(cfg, "x", steps_override=4).reconsult_gap == 4


@pytest.mark.parametrize("tool,args,expected", [
    ("exec", {"command": "git commit -m x"}, True),
    ("exec", {"command": "git -C repo push origin develop"}, True),
    ("exec", {"command": "git reset --hard HEAD~1"}, True),
    ("exec", {"command": "rm -rf build"}, True),
    ("exec", {"command": "rm -fr build"}, True),
    ("exec", {"command": "Remove-Item x -Recurse -Force"}, True),
    ("exec", {"command": "git status"}, False),
    ("exec", {"command": "git diff --stat"}, False),
    ("exec", {"command": "rm file.txt"}, False),
    ("write_file", {"path": "a"}, False),
    ("git_commit", {}, True),
])
def test_irreversible_call_detection(tool: str, args: dict[str, Any], expected: bool) -> None:
    assert policy.is_irreversible_call(tool, args) is expected


# ---------- D1: budget refill ----------

def test_budget_regrows_with_work_steps(env) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", max_uses=2, refill_steps=5)))
    session = env.sessions.get_or_create(KEY)
    assert advisor_state.effective(session).max_uses == 2  # type: ignore[union-attr]
    for _ in range(11):
        advisor_state.count_work_step(session)
    assert advisor_state.effective(session).max_uses == 4  # type: ignore[union-attr]
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", max_uses=2, refill_steps=0)))
    assert advisor_state.effective(session).max_uses == 2  # type: ignore[union-attr]


# ---------- hook: notes, pinned commitments, gates ----------

def _hook(env, **advisor: Any) -> tuple[CoworkerHook, Any]:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", **advisor)))
    session = env.sessions.get_or_create(KEY)
    hook = CoworkerHook(AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY))
    hook._genuine_text = "build it"  # a genuine user run
    return hook, session


async def _run_tool(hook: CoworkerHook, call_id: str, name: str, result: Any = "ok", **args: Any) -> None:
    call = ToolCallRequest(id=call_id, name=name, arguments=args)
    await hook.after_execute_tool(AgentHookContext(iteration=0, messages=[]), call, None, args, result)


def _notes(session: Any) -> dict[str, str]:
    return advisor_state.result_notes(session)


@pytest.mark.asyncio
async def test_first_write_without_consult_gets_a_note_once(env, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    hook, session = _hook(env)
    await _run_tool(hook, "w1", "write_file", path="a.py")
    await _run_tool(hook, "w2", "write_file", path="b.py")
    assert "first file write of this run" in _notes(session)["w1"]
    assert "w2" not in _notes(session)


@pytest.mark.asyncio
async def test_mid_run_checkpoint_fires_on_steps_and_on_distinct_files(env, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    hook, session = _hook(env, reconsult_gap=3, checkpoint_files=4)
    hook._consulted = True
    for i in range(3):
        await _run_tool(hook, f"e{i}", "exec", command="echo hi")
    assert "3 work steps" in _notes(session)["e2"]
    assert "e0" not in _notes(session) and "e1" not in _notes(session)
    await _run_tool(hook, "late", "exec", command="echo again")
    assert "late" not in _notes(session)  # once per window

    hook2, session2 = _hook(env, reconsult_gap=50, checkpoint_files=3)
    hook2._consulted = True
    for i in range(3):
        await _run_tool(hook2, f"f{i}", "write_file", path=f"f{i}.py")
    assert "3 files written" in _notes(session2)["f2"]

    # A real consult re-arms the window.
    await _run_tool(hook2, "adv", "advisor", ToolResult("ADVISOR (m) — advice 1/10:\n\nok"))
    assert hook2._gap == 0 and not hook2._files and hook2._reviewed_since_write is True


@pytest.mark.asyncio
async def test_executor_profile_tightens_the_checkpoint(env, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    hook, session = _hook(env, reconsult_gap=12, executor_profiles={"*flash*": ExecutorProfile(reconsult_gap=2)})
    hook._consulted = True
    hook._last_runtime = SimpleNamespace(model="gemini-3.8-flash-tiered")
    await _run_tool(hook, "a", "exec", command="x")
    await _run_tool(hook, "b", "exec", command="y")
    assert "2 work steps" in _notes(session)["b"]


@pytest.mark.asyncio
async def test_advisor_checkpoint_and_stop_verdict_notes(env, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    hook, session = _hook(env, mid_run_checkpoints=False)
    hook._consulted = True
    _, parsed = advisor_ledger.parse_ledger(
        'x\n```json\n{"verdict": "stop", "must_fix": ["wrong approach"], "next_checkpoint": "before_write:webui/src/**"}\n```'
    )
    assert parsed is not None
    advisor_state.apply_ledger(session, parsed)
    await _run_tool(hook, "w", "write_file", path="C:\\p\\webui\\src\\a.tsx")
    note = _notes(session)["w"]
    assert "advisor verdict is STOP (wrong approach)" in note
    assert "the advisor asked to be consulted at this point (before_write:webui/src/**)" in note
    await _run_tool(hook, "w2", "write_file", path="webui/src/b.tsx")
    assert "asked to be consulted" not in _notes(session)["w2"]  # fired once until the next consult
    assert "STOP" in _notes(session)["w2"]  # the stop reminder stays on every write


@pytest.mark.asyncio
async def test_steering_is_inert_for_automated_runs_brainstorm_and_when_off(env, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    hook, session = _hook(env)
    hook._genuine_text = None
    await _run_tool(hook, "w", "write_file", path="a.py")
    assert not _notes(session)

    hook, session = _hook(env)
    advisor_state.set_mode(session, advisor_state.MODE_BRAINSTORM)
    await _run_tool(hook, "w", "write_file", path="a.py")
    assert not _notes(session)

    hook, session = _hook(env, mid_run_checkpoints=False, ledger=False)
    await _run_tool(hook, "w", "write_file", path="a.py")
    assert not _notes(session)


def test_transform_request_pins_commitments_and_annotates_notes_idempotently(env) -> None:
    hook, session = _hook(env)
    _, parsed = advisor_ledger.parse_ledger(ADVICE)
    assert parsed is not None
    advisor_state.apply_ledger(session, parsed)
    advisor_state.add_result_note(session, "t1", "[nanobot-advisor] 12 work steps — call advisor() now.")
    messages = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "go"},
        {"role": "tool", "tool_call_id": "t1", "content": "RESULT"},
        {"role": "tool", "tool_call_id": "t2", "content": "OTHER"},
    ]
    ctx = AgentHookContext(iteration=0, messages=messages)
    out, _ = hook.transform_request(ctx, messages, None, stateful=False)
    system = out[0]["content"]
    assert "## Advisor commitments (open)" in system
    assert "CoworkerSettings.tsx still reads coding.agy" in system and "run bun run test" in system
    assert out[2]["content"].endswith("[nanobot-advisor] 12 work steps — call advisor() now.")
    assert out[3]["content"] == "OTHER"
    again, _ = hook.transform_request(ctx, out, None, stateful=False)
    assert again[2]["content"].count("[nanobot-advisor]") == 1

    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", ledger=False)))
    off, _ = hook.transform_request(ctx, messages, None, stateful=False)
    assert "## Advisor commitments (open)" not in off[0]["content"]


def _iter_context(messages: list[dict[str, Any]]) -> AgentHookContext:
    return AgentHookContext(iteration=1, messages=messages)


def test_done_gate_fires_once_when_items_are_open_and_work_was_done(env, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    hook, session = _hook(env, review_nudge=False)
    _, parsed = advisor_ledger.parse_ledger(ADVICE)
    assert parsed is not None
    advisor_state.apply_ledger(session, parsed)
    work = [{"role": "user", "content": "go"}, _assistant(_call("1", "write_file", path="a.py"))]
    hook._iter_ctx = _iter_context(work)
    first = hook.continuation()
    assert first is not None and first.startswith(policy.ADVISOR_REVIEW_MARKER)
    assert "OPEN items" in first and "CoworkerSettings.tsx still reads coding.agy" in first
    assert advisor_state.review_nudge(session)["kind"] == "done_gate"  # type: ignore[index]
    assert hook.continuation() is None  # once per run


def test_done_gate_stays_quiet_without_work_or_open_items_or_ledger_flag(env, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    work = [{"role": "user", "content": "go"}, _assistant(_call("1", "write_file", path="a.py"))]
    hook, session = _hook(env, review_nudge=False)
    _, parsed = advisor_ledger.parse_ledger(ADVICE)
    assert parsed is not None
    advisor_state.apply_ledger(session, parsed)
    hook._iter_ctx = _iter_context([{"role": "user", "content": "just a question"}])
    assert hook.continuation() is None  # stale items must not nag an answer-only run

    closed = {**parsed, "must_fix": [], "verify": []}
    advisor_state.apply_ledger(session, closed)
    hook._iter_ctx = _iter_context(work)
    assert hook.continuation() is None

    advisor_state.apply_ledger(session, parsed)
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", review_nudge=False, ledger=False)))
    assert hook.continuation() is None


@pytest.mark.asyncio
async def test_commit_gate_blocks_once_after_unreviewed_writes(env, monkeypatch, repo) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    monkeypatch.setattr("nanobot.coworker.hook.project_root_for", lambda session: repo)
    hook, session = _hook(env)
    ctx = AgentHookContext(iteration=0, messages=[])
    commit = ToolCallRequest(id="c1", name="exec", arguments={"command": "git commit -am x"})

    assert await hook.before_execute_tool(ctx, commit, None, commit.arguments) is None  # nothing written yet
    await _run_tool(hook, "w1", "write_file", path="a.py")
    blocked = await hook.before_execute_tool(ctx, commit, None, commit.arguments)
    assert blocked is not None
    payload = json.loads(blocked)
    assert payload["status"] == "advisor_review_required" and "git status --short" in payload["git"]
    assert await hook.before_execute_tool(ctx, commit, None, commit.arguments) is None  # repeat goes through

    await _run_tool(hook, "w2", "write_file", path="a.py")  # new write: gate re-arms
    assert await hook.before_execute_tool(ctx, commit, None, commit.arguments) is not None
    await _run_tool(hook, "w3", "write_file", path="a.py")
    await _run_tool(hook, "adv", "advisor", ToolResult("ADVISOR (m) — advice 1/10:\n\nok"))
    assert await hook.before_execute_tool(ctx, commit, None, commit.arguments) is None  # reviewed

    harmless = ToolCallRequest(id="c2", name="exec", arguments={"command": "git status"})
    await _run_tool(hook, "w4", "write_file", path="a.py")
    assert await hook.before_execute_tool(ctx, harmless, None, harmless.arguments) is None


@pytest.mark.asyncio
async def test_commit_gate_respects_flags_budget_and_profile(env, monkeypatch, repo) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    monkeypatch.setattr("nanobot.coworker.hook.project_root_for", lambda session: repo)
    ctx = AgentHookContext(iteration=0, messages=[])
    commit = ToolCallRequest(id="c1", name="exec", arguments={"command": "git push"})

    for advisor in (
        {"commit_gate": False},
        {"max_uses": 1},  # budget spent below
        {"executor_profiles": {"*": ExecutorProfile(commit_gate=False)}},
    ):
        hook, session = _hook(env, **advisor)
        hook._last_runtime = SimpleNamespace(model="some-executor")
        if "max_uses" in advisor:
            advisor_state.count_use(session)
        await _run_tool(hook, "w", "write_file", path="a.py")
        assert await hook.before_execute_tool(ctx, commit, None, commit.arguments) is None, advisor


@pytest.mark.asyncio
async def test_composite_hook_short_circuits_on_the_first_replacement() -> None:
    from nanobot.agent.hook import AgentHook

    class Blocker(AgentHook):
        async def before_execute_tool(self, context, tool_call, tool, params):  # type: ignore[override]
            return "BLOCKED"

    class Boom(AgentHook):
        async def before_execute_tool(self, context, tool_call, tool, params):  # type: ignore[override]
            raise RuntimeError("bug in a hook")

    call = ToolCallRequest(id="1", name="exec", arguments={})
    ctx = AgentHookContext(iteration=0, messages=[])
    assert await CompositeHook([AgentHook(), Boom(), Blocker()]).before_execute_tool(ctx, call, None, {}) == "BLOCKED"
    assert await CompositeHook([AgentHook(), Boom()]).before_execute_tool(ctx, call, None, {}) is None


@pytest.mark.asyncio
async def test_executor_skips_the_tool_when_a_hook_replaces_it() -> None:
    from nanobot.agent.hook import AgentHook
    from nanobot.agent.tools import execution

    class Blocker(AgentHook):
        async def before_execute_tool(self, context, tool_call, tool, params):  # type: ignore[override]
            return "REVIEW REQUIRED"

    ran: list[str] = []

    class Tools:
        def prepare_call(self, name: str, args: Any) -> tuple[Any, Any, None]:
            return SimpleNamespace(execute=lambda **kw: ran.append("tool")), args, None

        async def execute(self, name: str, args: Any) -> str:
            ran.append("registry")
            return "x"

    result, event = await execution._execute_tool_call(
        Tools(), ToolCallRequest(id="1", name="exec", arguments={"command": "git commit"}),  # type: ignore[arg-type]
        {}, {}, Blocker(), AgentHookContext(iteration=0, messages=[]), lambda: {},
    )
    assert result == "REVIEW REQUIRED" and event["status"] == "error" and not ran


# ---------- phase 0 ----------

@pytest.mark.asyncio
async def test_every_tool_result_size_is_recorded(env, monkeypatch) -> None:
    rows: list[dict[str, Any]] = []
    monkeypatch.setattr(metrics_store, "record_tool_result", lambda **kw: rows.append(kw))
    hook, _ = _hook(env)
    await _run_tool(hook, "r1", "read_file", "x" * 9000, path="a.py")
    await _run_tool(hook, "r2", "rg", ToolResult("boom", is_error=True), args=["x"])
    assert rows[0] == {"tool": "read_file", "result_chars": 9000, "elided": True, "is_error": False}
    assert rows[1]["tool"] == "rg" and rows[1]["is_error"] is True and rows[1]["elided"] is False
