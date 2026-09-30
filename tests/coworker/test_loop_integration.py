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
