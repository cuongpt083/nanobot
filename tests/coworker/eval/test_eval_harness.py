"""Unit and integration tests for coworker evaluation harness."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agent.conftest import make_loop

from nanobot.coworker import runtime
from nanobot.coworker.config import (
    CoworkerConfig,
    RoomAgentConfig,
    RoomConfig,
    set_coworker_config_override,
)
from nanobot.coworker.room import scheduler
from nanobot.coworker.room.tools import RoomDelegateTool, RoomStateTool
from nanobot.providers.base import LLMResponse, ToolCallRequest
from scripts.coworker_eval import (
    PROTECTED_OUTPUTS,
    CoworkerEvaluator,
    ProviderIncidentCounter,
    RunLog,
    ScenarioRunResult,
    UsageMeter,
    extract_final_output,
    get_tokens_since_id,
    main,
    remove_scratch_sessions,
    review_status,
    room_busy,
    run_result_from_dict,
    stop_room_tasks,
    turn_pending,
    wait_for_review,
    wait_room_settled,
)

SCENARIOS_DIR = Path(__file__).parent / "scenarios"


class FakeSubagents:
    def __init__(self, script: dict[str, list[str]]) -> None:
        self.script = script
        self.calls: list[tuple[str, str]] = []

    async def run_inline(self, *, task: str, label: str, **kwargs: object) -> str:
        agent = label.removeprefix("room:")
        self.calls.append((agent, task))
        return self.script[agent].pop(0)


def test_load_all_scenarios() -> None:
    evaluator = CoworkerEvaluator(scenarios_dir=SCENARIOS_DIR, dry_run=True)
    scenarios = evaluator.load_scenarios()

    assert len(scenarios) == 7
    ids = {s["id"] for s in scenarios}
    assert "edutech-course" in ids
    assert "nutritech-plan" in ids
    assert "script-update" in ids
    assert "crm-followup" in ids
    assert "presale-design" in ids
    assert "persona-nutri" in ids
    assert "persona-delegation" in ids

    # Check hash is generated
    for sc in scenarios:
        assert len(sc["_file_hash"]) == 12

    # Filter test
    filtered = evaluator.load_scenarios(scenario_slug="nutritech-plan")
    assert len(filtered) == 1
    assert filtered[0]["id"] == "nutritech-plan"


def test_judge_prompt_and_parser() -> None:
    evaluator = CoworkerEvaluator(scenarios_dir=SCENARIOS_DIR, dry_run=True)
    scenario = {
        "id": "test",
        "title": "Test Title",
        "prompt": "Test Prompt",
        "expected_agents": ["researcher"],
        "rubric": {"criteria": [{"name": "C1", "description": "D1"}]},
        "constraints": ["No medical"],
    }
    prompt = evaluator._build_judge_prompt(scenario, "Transcript here", ["researcher"])
    assert "Test Title" in prompt
    assert "Transcript here" in prompt
    assert "No medical" in prompt

    judge_output = """```json
    {
      "scores": {"C1": 4.5},
      "overall_score": 4.5,
      "constraint_violations": [],
      "reasoning": "Well structured."
    }
    ```"""
    overall, scores, violations, reasoning, err = evaluator._parse_judge_response(judge_output)
    assert overall == 4.5
    assert scores["C1"] == 4.5
    assert violations == []
    assert reasoning == "Well structured."
    assert err == ""

    wrapped = 'Advisor review: ok.\n{"scores": {"C1": 2.0}, "overall_score": 2.0, "reasoning": "x"}\nDone.'
    overall, scores, _, _, err = evaluator._parse_judge_response(wrapped)
    assert (overall, scores, err) == (2.0, {"C1": 2.0}, "")

    overall, scores, _, _, err = evaluator._parse_judge_response("Advisor review only, no JSON")
    assert err and overall == 0.0 and scores == {}


@pytest.mark.asyncio
async def test_eval_harness_dry_run(tmp_path: Path) -> None:
    evaluator = CoworkerEvaluator(scenarios_dir=SCENARIOS_DIR, dry_run=True)

    result = await evaluator.run_all(scenario_slug="edutech-course", num_runs=1)
    assert "metadata" in result
    assert result["metadata"]["dry_run"] is True
    assert "edutech-course" in result["scenarios"]

    sc_summary = result["scenarios"]["edutech-course"]
    assert sc_summary["runs_count"] == 1
    assert sc_summary["mean_routing_accuracy"] == 1.0
    assert sc_summary["mean_quality_score"] == 5.0
    assert sc_summary["file_hash"] != ""
    assert len(sc_summary["runs"]) == 1


@pytest.mark.asyncio
async def test_room_eval_loop_integration(tmp_path: Path) -> None:
    """Test full cycle: coordinator delegation -> background guest -> review turn -> settle."""
    cfg = CoworkerConfig(
        room=RoomConfig(
            enabled=True,
            agents=[
                RoomAgentConfig(id="researcher", name="Researcher", bio="finds facts"),
                RoomAgentConfig(id="writer", name="Writer", bio="writes copy"),
            ],
        )
    )
    set_coworker_config_override(cfg)

    loop = make_loop(tmp_path)
    loop.tools.register(RoomDelegateTool())
    loop.tools.register(RoomStateTool())

    fake_subagents = FakeSubagents({"researcher": ["Market facts found."]})
    runtime.set_services(
        runtime.CoworkerServices(
            workspace=tmp_path,
            bus=loop.bus,
            sessions=loop.sessions,
            subagents=fake_subagents,  # type: ignore[arg-type]
            provider_snapshot_loader=None,
        )
    )

    session_key = "eval:test:room_loop_1"
    session = loop.sessions.get_or_create(session_key)
    scheduler.set_armed(session, True)

    provider = loop.provider
    provider.provider_name = "test"
    # Round 1: Coordinator calls room_delegate to researcher
    # Round 2: Coordinator finishes initial turn
    # Round 3: Review turn ([auto-room]) produces final consolidated reply
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="call_del",
                    name="room_delegate",
                    arguments={
                        "agent": "researcher",
                        "task": "research facts",
                        "context": (
                            "User already decided: no medical diagnosis, low budget, "
                            "deliver via Zalo each morning, keep the tone practical."
                        ),
                    },
                )
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="I have delegated fact-finding to @researcher."),
        LLMResponse(content="Final consolidated report after reviewing @researcher's findings."),
    ])

    loop_task = asyncio.create_task(loop.run())
    try:
        # User prompt triggers coordinator turn
        res = await loop.process_direct("Please research the market and draft report.", session_key=session_key)
        assert "delegated" in res.content

        # Wait for room run and coordinator review to settle using the evaluator's own function
        await wait_room_settled(session_key, timeout=5.0, poll_interval=0.1)

        # Verify guest ran
        assert [agent for agent, _ in fake_subagents.calls] == ["researcher"]

        # Verify outcome was recorded in snapshot
        snap = scheduler.room_snapshot(session_key)
        assert len(snap.recent) == 1
        assert snap.recent[0].agent_id == "researcher"
        assert snap.recent[0].state == "done"

        # Verify review turn occurred in session history
        messages = loop.sessions.get_or_create(session_key).messages
        assert any("[auto-room]" in str(m.get("content", "")) for m in messages)
        assert any("Final consolidated report" in str(m.get("content", "")) for m in messages)

    finally:
        set_coworker_config_override(None)
        runtime.set_services(None)
        scheduler.reset_rooms()
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await loop.aclose()


def test_token_tracking_delta(tmp_path: Path) -> None:
    from nanobot.llm_usage.models import LLMCallRecord
    from nanobot.llm_usage.store import LLMUsageStore
    from nanobot.providers.base import LLMUsage

    db_path = tmp_path / "test_llm_usage.db"
    store = LLMUsageStore(db_path)

    # Initial baseline record
    now_ms = int(time.time() * 1000)
    rec1 = LLMCallRecord(
        started_at_ms=now_ms,
        duration_ms=100,
        provider="test",
        model="m1",
        source="user",
        stream=False,
        finish_reason="stop",
        usage=LLMUsage.reported(input_tokens=100, output_tokens=50),
    )
    store.record(rec1)
    cur = store._connect().execute("SELECT MAX(id) FROM llm_calls")
    start_id = int(cur.fetchone()[0])

    # Record inside eval run with reported tokens
    rec2 = LLMCallRecord(
        started_at_ms=now_ms + 1000,
        duration_ms=200,
        provider="test",
        model="m2",
        source="user",
        stream=False,
        finish_reason="stop",
        usage=LLMUsage.reported(input_tokens=300, output_tokens=80),
    )
    store.record(rec2)

    # Record inside eval run with estimated tokens
    rec3 = LLMCallRecord(
        started_at_ms=now_ms + 2000,
        duration_ms=150,
        provider="test",
        model="m3",
        source="user",
        stream=False,
        finish_reason="stop",
        usage=LLMUsage(
            input_tokens=50,
            output_tokens=20,
            total_tokens=70,
            reported_tokens=0,
            estimated_tokens=70,
        ),
    )
    store.record(rec3)

    import unittest.mock
    with unittest.mock.patch("scripts.coworker_eval.get_llm_usage_store", return_value=store):
        tin, tout, ttot, trep, test = get_tokens_since_id(start_id)
        assert tin == 350
        assert tout == 100
        assert ttot == 450
        assert trep == 380
        assert test == 70


# ---------- Phase 0 readiness: the harness must measure what it claims to measure ----------


def _result(**overrides: object) -> ScenarioRunResult:
    base: dict[str, object] = dict(
        run_idx=1, duration_s=1.0, tokens_in=1, tokens_out=1, total_tokens=2, reported_tokens=2,
        estimated_tokens=0, delegations=["a"], routing_accuracy=1.0, revision_count=0,
        quality_score=4.0, criteria_scores={}, constraint_violations=[], judge_reasoning="", content="x",
        review_completed=True,
    )
    base.update(overrides)
    return ScenarioRunResult(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_settle_waits_for_a_slow_review_turn(tmp_path: Path) -> None:
    """The review turn is injected after the room task ends; a room-only check returns too early."""
    cfg = CoworkerConfig(
        room=RoomConfig(enabled=True, agents=[RoomAgentConfig(id="researcher", name="R", bio="facts")])
    )
    set_coworker_config_override(cfg)
    loop = make_loop(tmp_path)
    loop.tools.register(RoomDelegateTool())
    loop.tools.register(RoomStateTool())
    runtime.set_services(
        runtime.CoworkerServices(
            workspace=tmp_path,
            bus=loop.bus,
            sessions=loop.sessions,
            subagents=FakeSubagents({"researcher": ["Market facts found."]}),  # type: ignore[arg-type]
            provider_snapshot_loader=None,
        )
    )
    session_key = "eval:test:slow_review"
    scheduler.set_armed(loop.sessions.get_or_create(session_key), True)

    responses = [
        LLMResponse(
            content="",
            tool_calls=[ToolCallRequest(
                id="call_del", name="room_delegate",
                arguments={
                    "agent": "researcher", "task": "research facts",
                    "context": (
                        "User already decided: no medical diagnosis, low budget, "
                        "deliver via Zalo each morning, keep the tone practical."
                    ),
                },
            )],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="Delegated to @researcher."),
        LLMResponse(content="Final consolidated report."),
    ]

    async def slow_review(*_args: object, **_kwargs: object) -> LLMResponse:
        response = responses.pop(0)
        if not responses:  # the review turn is the last call: make it take a while
            await asyncio.sleep(0.8)
        return response

    loop.provider.provider_name = "test"
    loop.provider.chat_stream_with_retry = AsyncMock(side_effect=slow_review)
    loop_task = asyncio.create_task(loop.run())
    try:
        await loop.process_direct("Research the market.", session_key=session_key)

        def final_text() -> str:
            return extract_final_output(loop.sessions.get_or_create(session_key).messages)

        # Room-only settle (the old behaviour) returns while the review is still running.
        assert await wait_room_settled(session_key, timeout=10.0, poll_interval=0.05)
        assert final_text() != "Final consolidated report."

        # Counting the turn flag and the inbound queue waits for the consolidated report.
        assert await wait_room_settled(
            session_key,
            timeout=10.0,
            poll_interval=0.05,
            extra_busy=lambda: turn_pending(session_key, loop.bus),
            quiet_period=0.4,
        )
        messages = loop.sessions.get_or_create(session_key).messages
        assert extract_final_output(messages) == "Final consolidated report."
        assert review_status(messages) == (True, True)
    finally:
        set_coworker_config_override(None)
        runtime.set_services(None)
        scheduler.reset_rooms()
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await loop.aclose()


@pytest.mark.asyncio
async def test_settle_times_out_while_extra_busy() -> None:
    assert not await wait_room_settled("eval:none", timeout=0.3, poll_interval=0.05, extra_busy=lambda: True)
    assert await wait_room_settled("eval:none", timeout=0.3, poll_interval=0.05, extra_busy=lambda: False)


def test_final_output_and_review_status() -> None:
    assert extract_final_output([]) == ""
    msgs: list[dict[str, object]] = [
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "hand-off"},
    ]
    assert review_status(msgs) == (False, False)
    assert extract_final_output(msgs) == "hand-off"

    msgs.append({"role": "user", "content": "[auto-room] Your teammates finished"})
    assert review_status(msgs) == (True, False)  # injected but no reply yet
    msgs += [
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "ok"},
    ]
    assert review_status(msgs) == (True, False)  # a tool call is not a report
    assert extract_final_output(msgs) == "hand-off"
    msgs.append({"role": "assistant", "content": [{"type": "text", "text": "final report"}]})
    assert review_status(msgs) == (True, True)
    assert extract_final_output(msgs) == "final report"


def test_usage_meter_counts_every_provider_and_ignores_the_shared_db() -> None:
    from types import SimpleNamespace

    meter = UsageMeter()
    usage = SimpleNamespace(
        input_tokens=100, output_tokens=10, total_tokens=110, reported_tokens=110, estimated_tokens=0
    )
    meter.record(SimpleNamespace(provider="gemini", model="flash", usage=usage))
    meter.record(SimpleNamespace(provider="anthropic", model="sonnet", usage=usage))
    meter.record(SimpleNamespace(provider="anthropic", model="sonnet", usage=None))  # no usage reported
    assert meter.calls == 3
    assert meter.totals() == (200, 20, 220, 220, 0)
    assert meter.by_model["anthropic/sonnet"]["calls"] == 2
    assert meter.by_model["anthropic/sonnet"]["total_tokens"] == 110
    meter.reset()
    assert meter.totals() == (0, 0, 0, 0, 0) and meter.by_model == {}


@pytest.mark.asyncio
async def test_judge_is_a_direct_call_that_retries_and_never_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = CoworkerEvaluator(scenarios_dir=SCENARIOS_DIR)  # live mode, no dry run

    def _no_bot() -> None:
        raise AssertionError("the judge must not run inside an AgentLoop")

    monkeypatch.setattr(ev, "_make_bot", _no_bot)
    prompts: list[str] = []
    answers = ["Advisor review only, no JSON", '{"overall_score": 4.0, "scores": {"C1": 4.0}, "reasoning": "ok"}']

    async def fake_call(prompt: str) -> str:
        prompts.append(prompt)
        return answers[len(prompts) - 1]

    monkeypatch.setattr(ev, "_judge_call", fake_call)
    scenario = {"id": "t", "prompt": "p", "rubric": {}}
    overall, scores, _, _, err = await ev._judge_eval(scenario, "HAND-OFF", ["a"], "SPECIALIST TEXT", "FINAL REPORT")
    assert (overall, scores, err) == (4.0, {"C1": 4.0}, "")
    assert len(prompts) == 2
    assert all(t in prompts[0] for t in ("HAND-OFF", "SPECIALIST TEXT", "FINAL REPORT"))

    async def always_bad(prompt: str) -> str:
        return "no json at all"

    monkeypatch.setattr(ev, "_judge_call", always_bad)
    overall, _, _, _, err = await ev._judge_eval(scenario, "x", [], "", "")
    assert overall == 0.0 and err  # an error, never the old 3.0 default

    async def raising(prompt: str) -> str:
        raise RuntimeError("provider down")

    monkeypatch.setattr(ev, "_judge_call", raising)
    _, _, _, _, err = await ev._judge_eval(scenario, "x", [], "", "")
    assert "provider down" in err


def test_run_log_roundtrip_filters_by_arm_error_and_torn_lines(tmp_path: Path) -> None:
    path = tmp_path / "out.json.runs.jsonl"
    arm = {"runner": "r", "judge": "j", "advisor": "a"}
    log = RunLog(path, arm)
    log.append("s", 1, "h1", _result(run_idx=1))
    log.append("s", 2, "h1", _result(run_idx=2, judge_error="unparseable"))
    log.append("s", 3, "h1", _result(run_idx=3, run_error="Boom"))
    log.append("s", 1, "OLD-HASH", _result(run_idx=1))
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"scenario_id": "s", "run_idx"')  # killed mid-write

    loaded = log.load()
    assert set(loaded) == {("s", 1, "h1"), ("s", 1, "OLD-HASH")}  # failed runs are re-run on resume
    assert run_result_from_dict(loaded[("s", 1, "h1")]).quality_score == 4.0
    assert RunLog(path, {**arm, "advisor": "off"}).load() == {}  # never mix arms
    assert run_result_from_dict({**loaded[("s", 1, "h1")], "future_field": 1}).run_idx == 1


@pytest.mark.asyncio
async def test_resume_reuses_finished_runs_and_isolates_crashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    arm = {"runner": "r", "judge": "j", "advisor": "a"}
    path = tmp_path / "x.runs.jsonl"
    first = CoworkerEvaluator(scenarios_dir=SCENARIOS_DIR, dry_run=True, run_log=RunLog(path, arm))
    scenario = first.load_scenarios("edutech-course")[0]
    await first.run_scenario(scenario, 2)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2

    second = CoworkerEvaluator(
        scenarios_dir=SCENARIOS_DIR, dry_run=True, run_log=RunLog(path, arm), resume=True
    )

    async def must_not_run(*_a: object, **_k: object) -> ScenarioRunResult:
        raise AssertionError("a finished run was executed again")

    monkeypatch.setattr(second, "run_scenario_once", must_not_run)
    summary = await second.run_scenario(scenario, 2)
    assert summary.runs_count == 2 and summary.judge_error_count == 0

    third = CoworkerEvaluator(scenarios_dir=SCENARIOS_DIR, dry_run=True)

    async def crash(*_a: object, **_k: object) -> ScenarioRunResult:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(third, "run_scenario_once", crash)
    crashed = await third.run_scenario(scenario, 2)
    assert crashed.runs_count == 2 and crashed.judge_error_count == 2  # excluded from quality means
    assert "provider exploded" in crashed.runs[0]["run_error"]


def test_main_never_overwrites_the_baseline_or_an_existing_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(*argv: str) -> int:
        monkeypatch.setattr("sys.argv", ["coworker_eval.py", *argv])
        return main()

    assert run() == 2  # a live run must name its output
    for protected in PROTECTED_OUTPUTS:
        assert run("-o", str(protected)) == 2
    existing = tmp_path / "done.json"
    existing.write_text("{}", encoding="utf-8")
    assert run("-o", str(existing)) == 2
    assert existing.read_text(encoding="utf-8") == "{}"
    assert "already exists" in capsys.readouterr().err


def test_preflight_reports_bad_scenarios_and_config_without_any_llm_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "broken.yaml").write_text("id: broken\nprompt: hi\n", encoding="utf-8")
    ev = CoworkerEvaluator(scenarios_dir=tmp_path, advisor_preset="off")

    def boom() -> None:
        raise RuntimeError("no config")

    monkeypatch.setattr(ev, "_eval_config", boom)
    problems = ev.preflight()
    assert any("broken" in p and "`rubric`" in p for p in problems)
    assert any("cannot load nanobot config" in p for p in problems)
    assert CoworkerEvaluator(scenarios_dir=tmp_path / "missing").preflight()[0].startswith("no scenarios")


def test_remove_scratch_sessions_only_deletes_the_scratch_namespace(tmp_path: Path) -> None:
    scratch = tmp_path / "coworker-eval-x"
    scratch.mkdir()
    real = tmp_path / "real-workspace"
    real.mkdir()
    sessions = tmp_path / "sessions"

    mine = sessions / "aaaa"
    mine.mkdir(parents=True)
    (mine / ".workspace").write_text(str(scratch), encoding="utf-8")
    (mine / "s.jsonl").write_text("{}", encoding="utf-8")
    theirs = sessions / "bbbb"
    theirs.mkdir()
    (theirs / ".workspace").write_text(str(real), encoding="utf-8")

    assert remove_scratch_sessions(None, scratch) is False
    assert remove_scratch_sessions(theirs, scratch) is False  # marker names another workspace
    assert theirs.exists()
    assert remove_scratch_sessions(sessions / "missing", scratch) is False
    assert remove_scratch_sessions(mine, scratch) is True
    assert not mine.exists() and theirs.exists()


@pytest.mark.asyncio
async def test_stop_room_tasks_cancels_the_room_run_and_its_teammates() -> None:
    """A timed-out room must not keep running into the next run (the cause of the v2 contamination)."""
    key = "eval:test:stop_room"
    room = scheduler._room(key)
    teammate_cancelled = asyncio.Event()

    async def teammate() -> None:
        try:
            await asyncio.sleep(3600)
        finally:
            teammate_cancelled.set()

    async def room_run() -> None:
        child = asyncio.create_task(teammate())
        try:
            await asyncio.sleep(3600)
        finally:
            child.cancel()
            await asyncio.gather(child, return_exceptions=True)

    room.task = asyncio.create_task(room_run())
    await asyncio.sleep(0)
    assert await stop_room_tasks(key) == 1
    assert room.task.done() and room.task.cancelled()
    assert teammate_cancelled.is_set()
    assert scheduler.room_id_for(key) not in scheduler._rooms
    assert await stop_room_tasks(key) == 0  # idempotent: nothing left to stop


def test_run_log_never_reuses_timed_out_or_incomplete_review_runs(tmp_path: Path) -> None:
    arm = {"runner": "r", "judge": "j", "advisor": "a"}
    log = RunLog(tmp_path / "x.runs.jsonl", arm)
    log.append("s", 1, "h", _result(run_idx=1, timed_out=True))
    log.append("s", 2, "h", _result(run_idx=2, delegations=["a"], review_completed=False))
    log.append("s", 3, "h", _result(run_idx=3, delegations=[], review_completed=False))  # no review expected
    log.append("s", 4, "h", _result(run_idx=4))
    assert set(log.load()) == {("s", 3, "h"), ("s", 4, "h")}


def test_provider_incident_counter_separates_provider_failures(tmp_path: Path) -> None:
    from types import SimpleNamespace

    counter = ProviderIncidentCounter()
    lines = [
        "Antigravity stream ended with finishReason=MALFORMED_FUNCTION_CALL and no output",
        "LLM transient error (attempt 1/3), retrying in 1s: error calling llm: antigravity stream ended with finishreason=malformed_function_call and no output",
        "LLM transient error (attempt 2/3), retrying in 2s: error calling llm: connection error.",
        "LLM request failed after 4 attempts, giving up: error calling llm: connection error.",
        "Fallback 'gemini-3.8-flash-medium' also failed",  # not a retry: ignored
    ]
    for text in lines:
        counter(SimpleNamespace(record={"message": text}))
    result = counter.apply(_result())
    assert (result.malformed_responses, result.provider_retries, result.connection_errors, result.provider_gave_up) == (
        1, 2, 1, 1,
    )


@pytest.mark.asyncio
async def test_wait_for_review_has_its_own_budget() -> None:
    """Stage 2 must return False when no report appears, and True as soon as one does."""
    from types import SimpleNamespace

    bus = SimpleNamespace(inbound_size=0)
    no_report = [{"role": "user", "content": "task"}, {"role": "assistant", "content": "hand-off"}]
    assert not await wait_for_review("eval:none", lambda: no_report, bus, timeout=0.3, poll_interval=0.05,
                                     quiet_period=0.05)

    with_report = no_report + [
        {"role": "user", "content": "[auto-room] Your teammates finished"},
        {"role": "assistant", "content": "final report"},
    ]
    assert await wait_for_review("eval:none", lambda: with_report, bus, timeout=5.0, poll_interval=0.05,
                                 quiet_period=0.05)


@pytest.mark.asyncio
async def test_room_busy_follows_the_room_task() -> None:
    key = "eval:test:busy"
    assert not room_busy(key)
    room = scheduler._room(key)
    room.task = asyncio.create_task(asyncio.sleep(3600))
    try:
        assert room_busy(key)
    finally:
        assert await stop_room_tasks(key) == 1
    assert not room_busy(key)
