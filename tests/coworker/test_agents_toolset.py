"""Phase 3: allow/deny tool policy, MCP sharing, isolated guest tool context."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.agent.tools.registry import ToolRegistry
from nanobot.coworker.agents.home import list_agent_skills, scaffold_agent_home
from nanobot.coworker.agents.toolset import (
    ALWAYS_ON_TOOLS,
    apply_policy,
    build_tools,
    matches_tool_name,
    mcp_server_from_allow_pattern,
    pattern_to_glob,
    subagent_tool_context,
)
from nanobot.coworker.config import NamePolicy, RoomAgentConfig
from nanobot.coworker.room.scheduler import RoomActor, current_room_actor
from nanobot.coworker.runtime import CoworkerServices, services, set_services


class _Named:
    def __init__(self, name: str) -> None:
        self.name = name


def _svc(tmp_path: Path, main_tools: ToolRegistry | None = None) -> CoworkerServices:
    return CoworkerServices(
        workspace=tmp_path,
        bus=object(),  # type: ignore[arg-type]
        sessions=object(),  # type: ignore[arg-type]
        subagents=None,
        provider_snapshot_loader=None,
        main_tools=main_tools,
    )


def _as_guest(agent_id: str = "helper"):
    return current_room_actor.set(
        RoomActor(room_id="r1", session_key="cli:direct", agent_id=agent_id)
    )


@pytest.mark.parametrize(
    ("name", "pattern", "expected"),
    [
        ("mcp_crm_search", "mcp:crm:*", True),
        ("mcp_crm_search", "mcp_crm_*", True),
        ("mcp_crm_search", "mcp:*", True),
        ("mcp_crm_search", "mcp:crm:search", True),
        ("mcp_other_x", "mcp:crm:*", False),
        ("read_file", "read_file", True),
        ("read_file", "read_*", True),
        ("Read_file", "read_file", False),
        ("spawn", "mcp:*", False),
        ("mcp_crm-prod_search", "mcp:crm-prod:*", True),
        ("mcp_crm_prod_search", "mcp:crm-prod:*", False),
    ],
)
def test_matches_tool_name(name: str, pattern: str, expected: bool) -> None:
    assert matches_tool_name(name, pattern) is expected


def test_sanitize_mcp_segment_matches_mcp_private_helper() -> None:
    from nanobot.agent.tools.mcp import _sanitize_name
    from nanobot.coworker.agents.toolset import _sanitize_mcp_segment

    for raw in ("crm-prod", "a.b c", "x__y", "CRM Server", "foo/bar", ""):
        assert _sanitize_mcp_segment(raw) == _sanitize_name(raw)


def test_pattern_to_glob_and_server_label() -> None:
    assert pattern_to_glob("mcp:crm:*") == "mcp_crm_*"
    assert pattern_to_glob("mcp:*") == "mcp_*"
    assert pattern_to_glob("mcp_crm_*") == "mcp_crm_*"
    assert mcp_server_from_allow_pattern("mcp:crm:*") == "crm"
    assert mcp_server_from_allow_pattern("mcp_crm_*") == "crm"
    assert mcp_server_from_allow_pattern("mcp:*") is None
    assert mcp_server_from_allow_pattern("read_file") is None


def test_empty_allow_keeps_legacy_subagent_set_without_mcp(tmp_path: Path) -> None:
    agent = RoomAgentConfig(id="helper")
    main = ToolRegistry()
    crm = _Named("mcp_crm_search")
    main.register(crm)  # type: ignore[arg-type]
    svc = _svc(tmp_path, main)
    token = _as_guest()
    try:
        registry = build_tools(agent, svc, project_root=tmp_path)
        baseline = build_tools(agent, _svc(tmp_path), project_root=tmp_path)
    finally:
        current_room_actor.reset(token)
    names = set(registry.tool_names)
    assert names == set(baseline.tool_names)
    assert "read_file" in names
    assert "mcp_crm_search" not in names
    assert "spawn" not in names
    assert "cron" not in names
    assert "message" not in names
    assert {"room_state", "room_delegate", "agents_list"} <= names


def test_allow_star_does_not_borrow_core_only_tools(tmp_path: Path) -> None:
    agent = RoomAgentConfig(id="helper", tools=NamePolicy(allow=["*"]))
    main = ToolRegistry()
    spawn = _Named("spawn")
    cron = _Named("cron")
    crm = _Named("mcp_crm_search")
    main.register(spawn)  # type: ignore[arg-type]
    main.register(cron)  # type: ignore[arg-type]
    main.register(crm)  # type: ignore[arg-type]
    token = _as_guest()
    try:
        registry = build_tools(agent, _svc(tmp_path, main), project_root=tmp_path)
    finally:
        current_room_actor.reset(token)
    names = set(registry.tool_names)
    assert "spawn" not in names
    assert "cron" not in names
    assert "mcp_crm_search" in names
    assert registry.get("mcp_crm_search") is crm


def test_allow_keeps_always_on_and_deny_wins(tmp_path: Path) -> None:
    agent = RoomAgentConfig(
        id="helper",
        tools=NamePolicy(allow=["read_file", "mcp_crm_*"], deny=["mcp_crm_*", "room_state"]),
    )
    main = ToolRegistry()
    crm = _Named("mcp_crm_search")
    other = _Named("mcp_other_x")
    main.register(crm)  # type: ignore[arg-type]
    main.register(other)  # type: ignore[arg-type]
    token = _as_guest()
    try:
        registry = build_tools(agent, _svc(tmp_path, main), project_root=tmp_path)
    finally:
        current_room_actor.reset(token)
    names = set(registry.tool_names)
    assert "read_file" in names
    assert "room_delegate" in names
    assert "agents_list" in names
    assert "room_state" not in names
    assert "mcp_crm_search" not in names
    assert "mcp_other_x" not in names
    assert registry.get("mcp_crm_search") is None


def test_mcp_wrappers_are_shared_not_copied(tmp_path: Path) -> None:
    agent = RoomAgentConfig(id="helper", tools=NamePolicy(allow=["mcp:crm:*"]))
    main = ToolRegistry()
    crm = _Named("mcp_crm_search")
    main.register(crm)  # type: ignore[arg-type]
    token = _as_guest()
    try:
        first = build_tools(agent, _svc(tmp_path, main), project_root=tmp_path)
        second = build_tools(agent, _svc(tmp_path, main), project_root=tmp_path)
    finally:
        current_room_actor.reset(token)
    assert first.get("mcp_crm_search") is crm
    assert second.get("mcp_crm_search") is crm
    assert main.get("mcp_crm_search") is crm


@pytest.mark.asyncio
async def test_unlisted_tool_execute_is_not_found(tmp_path: Path) -> None:
    agent = RoomAgentConfig(id="helper", tools=NamePolicy(allow=["read_file"]))
    token = _as_guest()
    try:
        registry = build_tools(agent, _svc(tmp_path), project_root=tmp_path)
    finally:
        current_room_actor.reset(token)
    result = await registry.execute("spawn", {})
    text = str(result).lower()
    assert "not found" in text
    assert "spawn" not in registry.tool_names


@pytest.mark.asyncio
async def test_fake_provider_outside_allowlist_is_not_executed(tmp_path: Path) -> None:
    from agent.runner_helpers import make_run_spec

    from nanobot.agent.runner import AgentRunner
    from nanobot.config.schema import AgentDefaults
    from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

    agent = RoomAgentConfig(id="helper", tools=NamePolicy(allow=["read_file"]))
    token = _as_guest()
    try:
        tools = build_tools(agent, _svc(tmp_path), project_root=tmp_path)
    finally:
        current_room_actor.reset(token)
    spawn = tools.get("spawn")
    assert spawn is None

    provider = MagicMock(spec=LLMProvider)
    calls = {"n": 0}

    async def chat_stream_with_retry(**_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallRequest(id="c1", name="spawn", arguments={"task": "x"})],
            )
        return LLMResponse(content="done")

    provider.chat_stream_with_retry = chat_stream_with_retry
    result = await AgentRunner().run(
        make_run_spec(
            provider,
            initial_messages=[{"role": "user", "content": "go"}],
            tools=tools,
            model="test-model",
            max_iterations=2,
            max_tool_result_chars=AgentDefaults().max_tool_result_chars,
        )
    )
    tool_msgs = [m for m in result.messages if m.get("role") == "tool"]
    assert tool_msgs
    assert "not found" in str(tool_msgs[0].get("content", "")).lower()


def test_deny_on_empty_allow_still_filters(tmp_path: Path) -> None:
    agent = RoomAgentConfig(id="helper", tools=NamePolicy(deny=["read_file"]))
    token = _as_guest()
    try:
        registry = build_tools(agent, _svc(tmp_path), project_root=tmp_path)
    finally:
        current_room_actor.reset(token)
    assert "read_file" not in registry.tool_names
    assert "write_file" in registry.tool_names


def test_apply_policy_always_on_exempt_from_allow_not_deny() -> None:
    registry = ToolRegistry()
    for name in ("read_file", "room_state", "room_delegate"):
        registry.register(_Named(name))  # type: ignore[arg-type]
    apply_policy(registry, NamePolicy(allow=["read_file"]), always=ALWAYS_ON_TOOLS)
    assert set(registry.tool_names) >= {"read_file", "room_state", "room_delegate"}
    apply_policy(registry, NamePolicy(deny=["room_delegate"]), always=ALWAYS_ON_TOOLS)
    assert "room_delegate" not in registry.tool_names


def test_two_guests_get_isolated_exec_and_file_state(tmp_path: Path) -> None:
    svc = _svc(tmp_path)
    first = subagent_tool_context(svc, tmp_path)
    second = subagent_tool_context(svc, tmp_path)
    assert first.exec_session_manager is not second.exec_session_manager
    assert first.file_state_store is not second.file_state_store


def test_build_tools_does_not_rebind_when_allow_borrows_mcp(tmp_path: Path) -> None:
    agent = RoomAgentConfig(id="helper", tools=NamePolicy(allow=["mcp_crm_*"]))
    main = ToolRegistry()
    main.register(_Named("mcp_crm_search"))  # type: ignore[arg-type]
    svc = _svc(tmp_path, main)
    set_services(svc)
    token = _as_guest()
    try:
        registry = build_tools(agent, svc, project_root=tmp_path)
        assert "mcp_crm_search" in registry.tool_names
        assert services() is svc
    finally:
        current_room_actor.reset(token)
        set_services(None)


def test_list_agent_skills_inherit_home_minus_deny(tmp_path: Path) -> None:
    agent = RoomAgentConfig(
        id="coach",
        home="agents/coach",
        skills={"inherit": ["cron", "weather"], "deny": ["weather"]},
    )
    scaffold_agent_home(tmp_path, agent)
    skill_dir = tmp_path / "agents" / "coach" / "skills" / "local-diet"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: local-diet\ndescription: d\n---\n", encoding="utf-8")
    assert list_agent_skills(agent, tmp_path) == ["cron", "local-diet"]
