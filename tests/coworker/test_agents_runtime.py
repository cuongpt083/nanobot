from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.config.schema import ToolsConfig
from nanobot.coworker.agents.home import scaffold_agent_home
from nanobot.coworker.agents.runtime import AgentRuntime, to_guest_result
from nanobot.coworker.agents.thread import AgentThreadStore
from nanobot.coworker.agents.toolset import build_tools, subagent_tool_context
from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.runtime import CoworkerServices, services, set_services
from nanobot.providers.base import LLMUsage
from nanobot.security.workspace_access import (
    build_workspace_scope,
    current_workspace_scope,
    workspace_sandbox_status,
)


def test_to_guest_result_maps_usage_and_tools() -> None:
    result = AgentRunResult(
        final_content="  done  ",
        messages=[],
        tools_used=["room_state", "read_file", "room_state"],
        usage=LLMUsage.estimated(input_tokens=11, output_tokens=7),
        stop_reason="completed",
    )
    guest = to_guest_result(result, RoomAgentConfig(id="helper"))
    assert guest.text == "done"
    assert guest.tools_used == ["room_state", "read_file"]
    assert guest.usage == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
    }


@pytest.mark.asyncio
async def test_runtime_persists_thread_for_home_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = RoomAgentConfig(id="specialist", home="agents/specialist", memory="thread")
    scaffold_agent_home(tmp_path, agent)
    cfg = CoworkerConfig(room=RoomConfig(agents=[agent]))
    svc = CoworkerServices(
        workspace=tmp_path,
        bus=None,  # type: ignore[arg-type]
        sessions=None,  # type: ignore[arg-type]
        subagents=None,
        provider_snapshot_loader=None,
    )
    runtime = AgentRuntime(svc, cfg)
    fake_result = AgentRunResult(
        final_content="first reply",
        messages=[],
        tools_used=["room_state"],
        usage=LLMUsage.estimated(input_tokens=3, output_tokens=2),
        stop_reason="completed",
    )
    runtime.runner.run = AsyncMock(return_value=fake_result)  # type: ignore[method-assign]
    monkeypatch.setattr("nanobot.coworker.agents.runtime.build_tools", lambda *a, **k: MagicMock())
    set_services(svc)
    before = id(svc)

    guest = await runtime.run(
        agent,
        "do the work",
        room_id="room1",
        session_key="cli:direct",
        channel="cli",
        chat_id="direct",
        project_root=tmp_path,
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )
    assert guest.text == "first reply"
    assert id(services()) == before
    history = AgentThreadStore(tmp_path, agent.id, "room1").recent(8)
    assert history == [
        {"role": "user", "content": "do the work"},
        {"role": "assistant", "content": "first reply"},
    ]


@pytest.mark.asyncio
async def test_runtime_skips_thread_when_memory_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = RoomAgentConfig(id="specialist", home="agents/specialist", memory="none")
    scaffold_agent_home(tmp_path, agent)
    cfg = CoworkerConfig(room=RoomConfig(agents=[agent]))
    svc = CoworkerServices(
        workspace=tmp_path,
        bus=None,  # type: ignore[arg-type]
        sessions=None,  # type: ignore[arg-type]
        subagents=None,
        provider_snapshot_loader=None,
    )
    runtime = AgentRuntime(svc, cfg)
    runtime.runner.run = AsyncMock(return_value=AgentRunResult(  # type: ignore[method-assign]
        final_content="ok",
        messages=[],
        stop_reason="completed",
    ))
    monkeypatch.setattr("nanobot.coworker.agents.runtime.build_tools", lambda *a, **k: MagicMock())
    await runtime.run(
        agent,
        "task",
        room_id="room1",
        session_key="cli:direct",
        channel="cli",
        chat_id="direct",
        project_root=tmp_path,
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )
    assert AgentThreadStore(tmp_path, agent.id, "room1").recent(8) == []


@pytest.mark.asyncio
async def test_runtime_binds_session_workspace_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = RoomAgentConfig(id="specialist", home="agents/specialist", memory="thread")
    scaffold_agent_home(tmp_path, agent)
    project = tmp_path / "proj"
    project.mkdir()
    cfg = CoworkerConfig(room=RoomConfig(agents=[agent]))
    svc = CoworkerServices(
        workspace=tmp_path,
        bus=None,  # type: ignore[arg-type]
        sessions=None,  # type: ignore[arg-type]
        subagents=None,
        provider_snapshot_loader=None,
        tools_config=ToolsConfig(restrict_to_workspace=False),
        workspace_sandbox=workspace_sandbox_status(
            restrict_to_workspace=False, workspace=tmp_path
        ),
    )
    runtime = AgentRuntime(svc, cfg)
    seen: dict[str, object] = {}

    async def fake_run(spec):  # type: ignore[no-untyped-def]
        seen["scope"] = current_workspace_scope()
        seen["workspace"] = spec.workspace
        return AgentRunResult(
            final_content="ok",
            messages=[],
            stop_reason="completed",
        )

    runtime.runner.run = fake_run  # type: ignore[method-assign]
    monkeypatch.setattr("nanobot.coworker.agents.runtime.build_tools", lambda *a, **k: MagicMock())
    scope = build_workspace_scope(project, "restricted")
    await runtime.run(
        agent,
        "task",
        room_id="room1",
        session_key="cli:direct",
        channel="cli",
        chat_id="direct",
        project_root=tmp_path,
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
        workspace_scope=scope,
    )
    assert seen["scope"] == scope
    assert seen["workspace"] == project.resolve()
    assert current_workspace_scope() is None


def test_subagent_tool_context_computes_sandbox_for_project_root(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    stale = workspace_sandbox_status(restrict_to_workspace=False, workspace=tmp_path)
    svc = CoworkerServices(
        workspace=tmp_path,
        bus=object(),  # type: ignore[arg-type]
        sessions=object(),  # type: ignore[arg-type]
        subagents=None,
        provider_snapshot_loader=None,
        tools_config=ToolsConfig(restrict_to_workspace=False),
        workspace_sandbox=stale,
    )
    ctx = subagent_tool_context(svc, project, restrict_to_workspace=True)
    assert ctx.config.restrict_to_workspace is True
    assert ctx.workspace_sandbox is not None
    assert ctx.workspace_sandbox.restrict_to_workspace is True
    assert Path(ctx.workspace_sandbox.workspace_root) == project.resolve()
    assert ctx.workspace_sandbox is not stale


def test_build_tools_does_not_rebind_services(tmp_path: Path) -> None:
    agent = RoomAgentConfig(id="specialist", home="agents/specialist")
    scaffold_agent_home(tmp_path, agent)
    svc = CoworkerServices(
        workspace=tmp_path,
        bus=object(),  # type: ignore[arg-type]
        sessions=object(),  # type: ignore[arg-type]
        subagents=None,
        provider_snapshot_loader=None,
        max_tool_result_chars=1234,
    )
    set_services(svc)
    try:
        registry = build_tools(agent, svc, project_root=tmp_path)
        assert "read_file" in registry.tool_names
        live = services()
        assert live is svc
        assert live is not None
        assert live.max_tool_result_chars == 1234
        assert live.bus is svc.bus
    finally:
        set_services(None)
