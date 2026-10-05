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
from scripts.coworker_eval import CoworkerEvaluator, get_tokens_since_id, wait_room_settled

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

    assert len(scenarios) == 6
    ids = {s["id"] for s in scenarios}
    assert "edutech-course" in ids
    assert "nutritech-plan" in ids
    assert "script-update" in ids
    assert "crm-followup" in ids
    assert "presale-design" in ids
    assert "persona-nutri" in ids

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
    overall, scores, violations, reasoning = evaluator._parse_judge_response(judge_output)
    assert overall == 4.5
    assert scores["C1"] == 4.5
    assert violations == []
    assert reasoning == "Well structured."


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
