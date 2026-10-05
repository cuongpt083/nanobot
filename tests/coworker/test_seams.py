"""Guards for the upstream seams the coworker extension depends on.

If an upstream merge drops one of these, the extension silently stops working;
these tests make that loud. See docs/coworker/README.md § Seams.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from agent.runner_helpers import make_run_spec

from nanobot.agent.hook import AgentHook, AgentHookContext, CompositeHook
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.turn_hooks import AgentTurnHookSpec, build_agent_turn_hook
from nanobot.command.builtin import register_builtin_commands
from nanobot.command.router import CommandRouter
from nanobot.config.schema import AgentDefaults
from nanobot.coworker.hook import CoworkerHook
from nanobot.providers.base import LLMProvider, LLMResponse


class _DropFirstUser(AgentHook):
    def transform_request(self, context, messages, tools, *, stateful):
        return [m for m in messages if m.get("content") != "drop me"], []


class _Boom(AgentHook):
    def transform_request(self, context, messages, tools, *, stateful):
        raise RuntimeError("broken transform")


@pytest.mark.asyncio
async def test_runner_sends_the_hook_transformed_payload() -> None:
    from nanobot.agent.runner import AgentRunner

    provider = MagicMock(spec=LLMProvider)
    provider.chat_stream_with_retry = AsyncMock(return_value=LLMResponse(content="done"))
    tools = MagicMock()
    tools.get_definitions.return_value = [{"type": "function", "function": {"name": "x"}}]

    result = await AgentRunner().run(make_run_spec(
        provider,
        initial_messages=[
            {"role": "user", "content": "drop me"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "keep me"},
        ],
        tools=tools,
        model="test-model",
        max_iterations=1,
        max_tool_result_chars=AgentDefaults().max_tool_result_chars,
        hook=CompositeHook([_Boom(), _DropFirstUser()]),
    ))

    sent = provider.chat_stream_with_retry.await_args.kwargs
    assert [m["content"] for m in sent["messages"]] == ["ok", "keep me"]
    assert sent["tools"] == []
    # The transcript itself is untouched.
    assert result.messages[0]["content"] == "drop me"


def test_composite_transform_is_a_pipeline() -> None:
    ctx = AgentHookContext(iteration=0, messages=[])
    messages, tools = CompositeHook([_Boom(), _DropFirstUser()]).transform_request(
        ctx, [{"role": "user", "content": "drop me"}], None, stateful=False
    )
    assert messages == [] and tools == []


def test_turn_hook_chain_includes_the_coworker_hook() -> None:
    hook = build_agent_turn_hook(AgentTurnHookSpec(session_key="cli:direct"))
    assert isinstance(hook, CompositeHook)
    assert any(isinstance(h, CoworkerHook) for h in hook._hooks)


def test_ephemeral_turns_skip_the_coworker_hook() -> None:
    hook = build_agent_turn_hook(AgentTurnHookSpec(session_key="dream:x", ephemeral=True))
    assert not isinstance(hook, CompositeHook)


def test_builtin_router_registers_coworker_commands() -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    for command in ("/advisor", "/room", "/workflow", "/ctx"):
        assert command in router._exact


def test_tool_loader_discovers_coworker_tools() -> None:
    names = {cls.__name__ for cls in ToolLoader().discover()}
    assert {
        "AdvisorTool", "AgentNotesTool", "AgentsListTool", "RoomDelegateTool", "RoomStateTool",
        "MarkContextWastedTool", "WorkflowRunTool", "WorkflowDistillTool",
    } <= names


def test_tool_context_exposes_main_registry(tmp_path) -> None:
    from agent.conftest import make_loop

    from nanobot.agent.tools.context import ToolContext
    from nanobot.coworker import runtime

    assert "tool_registry" in ToolContext.__dataclass_fields__
    loop = make_loop(tmp_path)
    try:
        svc = runtime.services()
        assert svc is not None
        assert svc.main_tools is loop.tools
    finally:
        runtime.set_services(None)
