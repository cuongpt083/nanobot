"""End-to-end through a real AgentLoop: tool registration, payload shaping, injected turns."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from agent.conftest import make_loop

from nanobot.coworker import runtime
from nanobot.coworker.config import CoworkerConfig, set_coworker_config_override
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _tool_names(call) -> set[str]:
    return {t["function"]["name"] for t in call.kwargs["tools"] or []}


@pytest.mark.asyncio
async def test_workflow_run_through_a_real_loop(tmp_path: Path) -> None:
    set_coworker_config_override(CoworkerConfig())
    wf = tmp_path / "workflows" / "greet"
    (wf / "steps").mkdir(parents=True)
    (wf / "workflow.md").write_text('---\nname: Greet\nstart: "[[hello]]"\n---\n')
    (wf / "steps" / "hello.md").write_text("---\ntype: end\n---\nSay hello to the user.\n")

    loop = make_loop(tmp_path)
    provider = loop.provider
    provider.provider_name = "test"
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=[ToolCallRequest(
            id="c1", name="workflow_run", arguments={"action": "start", "workflow": "greet"})],
            finish_reason="tool_calls"),
        LLMResponse(content="Started the workflow."),
        LLMResponse(content='Hello!\n```json\n{"greeted": true}\n```'),
    ])
    try:
        assert runtime.services() is not None  # bound when the loop registered its tools
        await loop.process_direct("run the greet workflow", session_key="cli:direct")

        first_request = provider.chat_stream_with_retry.await_args_list[0]
        names = _tool_names(first_request)
        assert "workflow_run" in names
        assert not names & {"advisor", "room_delegate", "room_state", "mark_context_wasted"}

        injected = await asyncio.wait_for(loop.bus.consume_inbound(), timeout=2)
        assert injected.channel == "system"
        assert injected.content.startswith("[auto-workflow:greet:hello]")
        assert injected.session_key_override == "cli:direct"

        await loop._process_message(injected)
        session = loop.sessions.get_or_create("cli:direct")
        assert "workflow" not in session.metadata.get("coworker", {})  # run finished → unbound
        assert any("[auto-workflow:greet:hello]" in str(m.get("content")) for m in session.messages)
    finally:
        set_coworker_config_override(None)
        runtime.set_services(None)
        await loop.aclose()


def _write_pair() -> list[ToolCallRequest]:
    return [
        ToolCallRequest(id="w1", name="write_file", arguments={"path": "a.txt", "content": "1"}),
        ToolCallRequest(id="w2", name="write_file", arguments={"path": "b.txt", "content": "2"}),
    ]


@pytest.mark.asyncio
async def test_in_run_advisor_nudge_stays_in_one_run(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from nanobot.coworker.config import AdvisorConfig

    set_coworker_config_override(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    monkeypatch.setattr(
        "nanobot.coworker.hook.runtime_for_preset",
        lambda preset: SimpleNamespace(model="strong-model"),
    )
    loop = make_loop(tmp_path)
    provider = loop.provider
    provider.provider_name = "test"
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=_write_pair(), finish_reason="tool_calls"),
        LLMResponse(content="done"),
        LLMResponse(content="done after review"),
    ])
    try:
        await loop.process_direct("build it", session_key="cli:direct")

        # The nudge was consumed inside the same run: three model rounds, no extra bus turn.
        assert provider.chat_stream_with_retry.await_count == 3
        assert loop.bus.inbound.empty()
        session = loop.sessions.get_or_create("cli:direct")
        markers = [m for m in session.messages if "[auto-advisor-review]" in str(m.get("content"))]
        assert len(markers) == 1
    finally:
        set_coworker_config_override(None)
        runtime.set_services(None)
        await loop.aclose()


@pytest.mark.asyncio
async def test_advisor_nudge_precedes_the_goal_continuation(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace

    from nanobot.coworker.config import AdvisorConfig

    set_coworker_config_override(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    monkeypatch.setattr(
        "nanobot.coworker.hook.runtime_for_preset",
        lambda preset: SimpleNamespace(model="strong-model"),
    )
    goal_calls = {"n": 0}

    def _goal_lines(_metadata):
        goal_calls["n"] += 1
        return ["Goal (active):", "keep going"] if goal_calls["n"] == 1 else []

    monkeypatch.setattr("nanobot.agent.loop.goal_state_runtime_lines", _goal_lines)
    loop = make_loop(tmp_path)
    provider = loop.provider
    provider.provider_name = "test"
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="", tool_calls=_write_pair(), finish_reason="tool_calls"),
        LLMResponse(content="done"),
        LLMResponse(content="done after review"),
        LLMResponse(content="done after goal"),
    ])
    try:
        await loop.process_direct("build it", session_key="cli:direct")

        assert provider.chat_stream_with_retry.await_count == 4
        assert loop.bus.inbound.empty()
        contents = [str(m.get("content")) for m in loop.sessions.get_or_create("cli:direct").messages]
        advisor_at = next(i for i, c in enumerate(contents) if "[auto-advisor-review]" in c)
        goal_at = next(i for i, c in enumerate(contents) if "active sustained goal" in c)
        assert advisor_at < goal_at
    finally:
        set_coworker_config_override(None)
        runtime.set_services(None)
        await loop.aclose()
