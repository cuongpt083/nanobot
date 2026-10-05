"""Tests for per-session persona support."""

from __future__ import annotations

import json
from typing import Any

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.hook import CoworkerHook
from nanobot.coworker.persona import get_persona_id, resolve_persona, set_persona_id
from nanobot.coworker.room import scheduler
from nanobot.coworker.session_api import apply_persona
from nanobot.coworker.status import coworker_session_status
from nanobot.session.model_selection import (
    SESSION_MODEL_PRESET_METADATA_KEY,
    model_preset_from_metadata,
)

KEY = "cli:direct"
CFG = CoworkerConfig(
    room=RoomConfig(
        agents=[
            RoomAgentConfig(
                id="researcher",
                name="Deep Researcher",
                emoji="🔎",
                bio="Fact checking & sources",
                preset="sonnet",
                instructions="Always cite sources.",
            ),
            RoomAgentConfig(
                id="writer",
                name="Marketing Writer",
                emoji="✍️",
                bio="Engaging copy",
                preset=None,
                instructions="Use energetic tone.",
            ),
        ]
    )
)


def test_set_and_resolve_persona(env) -> None:
    session = env.sessions.get_or_create(KEY)

    # 1. Unknown persona raises ValueError
    with pytest.raises(ValueError, match="unknown persona 'unknown'"):
        set_persona_id(session, "unknown", CFG)

    # 2. Valid persona with preset sets state and session metadata
    agent = set_persona_id(session, "researcher", CFG)
    assert agent is not None
    assert agent.id == "researcher"
    assert get_persona_id(session) == "researcher"
    assert resolve_persona(session, CFG) == agent
    assert session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "sonnet"
    assert model_preset_from_metadata(session.metadata) == "sonnet"

    # 3. Clearing persona resets state and metadata
    set_persona_id(session, None, CFG)
    assert get_persona_id(session) is None
    assert resolve_persona(session, CFG) is None
    assert SESSION_MODEL_PRESET_METADATA_KEY not in session.metadata


def test_persona_in_transform_request(env) -> None:
    env.configure(CFG)
    session = env.sessions.get_or_create(KEY)
    set_persona_id(session, "researcher", CFG)

    hook = CoworkerHook(
        AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    )
    agent_ctx = AgentHookContext(iteration=0, messages=[])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "BASE_PROMPT"},
        {"role": "user", "content": "Hello!"},
    ]

    out_msgs, _ = hook.transform_request(agent_ctx, messages, None, stateful=False)
    sys_content = out_msgs[0]["content"]
    assert "BASE_PROMPT" in sys_content
    assert "## Persona: Deep Researcher 🔎" in sys_content
    assert "Role: Fact checking & sources" in sys_content
    assert "Always cite sources." in sys_content


def test_persona_in_coworker_status(env) -> None:
    env.configure(CFG)
    session = env.sessions.get_or_create(KEY)
    set_persona_id(session, "researcher", CFG)

    status = coworker_session_status(session)
    assert status["persona"] is not None
    assert status["persona"]["id"] == "researcher"
    assert status["persona"]["name"] == "Deep Researcher"
    assert status["persona"]["emoji"] == "🔎"
    assert status["persona"]["preset"] == "sonnet"

    assert len(status["personas"]) == 2
    assert status["personas"][0]["id"] == "researcher"
    assert status["personas"][1]["id"] == "writer"

    coordinator = status["participants"][0]
    assert coordinator["id"] == "coordinator"
    assert coordinator["label"] == "🔎 Deep Researcher"
    assert coordinator["engine"] == "preset:sonnet"


def test_session_api_apply_persona(env) -> None:
    env.configure(CFG)
    session = env.sessions.get_or_create(KEY)

    # Apply valid persona
    apply_persona(session, {"persona": "writer"})
    assert get_persona_id(session) == "writer"
    assert SESSION_MODEL_PRESET_METADATA_KEY not in session.metadata  # preset is None

    # Apply "none" clears persona
    apply_persona(session, {"persona": "none"})
    assert get_persona_id(session) is None

    # Re-apply with researcher
    apply_persona(session, {"id": "researcher"})
    assert get_persona_id(session) == "researcher"
    assert session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "sonnet"


def test_persona_preset_preserves_user_override(env) -> None:
    session = env.sessions.get_or_create(KEY)

    # 1. Turn on researcher (sets preset to 'sonnet')
    set_persona_id(session, "researcher", CFG)
    assert session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "sonnet"

    # User manually overrides model preset to 'opus'
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "opus"

    # Clearing persona preserves user override
    set_persona_id(session, None, CFG)
    assert get_persona_id(session) is None
    assert session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "opus"

    # Re-enable researcher, user overrides, then switch to writer (no preset)
    set_persona_id(session, "researcher", CFG)
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "custom-model"
    set_persona_id(session, "writer", CFG)
    assert get_persona_id(session) == "writer"
    assert session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "custom-model"


def test_persona_preset_switch_and_legacy_fallback(env) -> None:
    session = env.sessions.get_or_create(KEY)

    # Switch from researcher (sonnet) to writer (no preset) when untouched
    set_persona_id(session, "researcher", CFG)
    assert session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] == "sonnet"
    set_persona_id(session, "writer", CFG)
    assert get_persona_id(session) == "writer"
    assert SESSION_MODEL_PRESET_METADATA_KEY not in session.metadata

    # Legacy state simulation: 'persona' is set, metadata preset matches agent, but 'persona_preset' missing
    from nanobot.coworker.runtime import session_state

    state = session_state(session)
    state["persona"] = "researcher"
    state.pop("persona_preset", None)
    session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = "sonnet"

    # Clearing persona falls back to old agent's preset and cleans it up
    set_persona_id(session, None, CFG)
    assert get_persona_id(session) is None
    assert SESSION_MODEL_PRESET_METADATA_KEY not in session.metadata


def test_persona_direct_mode_replaces_system_prompt_with_home_soul(env) -> None:
    from nanobot.coworker.agents.home import scaffold_agent_home

    agent = RoomAgentConfig(
        id="specialist",
        name="Specialist Agent",
        emoji="🔬",
        home="agents/specialist",
        bio="Deep scientific analysis",
    )
    scaffold_agent_home(env.workspace, agent)
    (env.workspace / "agents" / "specialist" / "SOUL.md").write_text(
        "# Specialist Soul Marker\nI am the specialized scientific assistant.",
        encoding="utf-8",
    )

    cfg = CoworkerConfig(room=RoomConfig(agents=[agent]))
    env.configure(cfg)
    env.bind()

    session = env.sessions.get_or_create(KEY)
    set_persona_id(session, "specialist", cfg)

    hook = CoworkerHook(
        AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    )
    agent_ctx = AgentHookContext(iteration=0, messages=[])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "ORIGINAL_WORKSPACE_PROMPT"},
        {"role": "user", "content": "Hello scientific assistant!"},
    ]

    out_msgs, _ = hook.transform_request(agent_ctx, messages, None, stateful=False)
    sys_content = str(out_msgs[0]["content"])

    # In direct mode, the original workspace prompt is replaced with the agent's home prompt
    assert "ORIGINAL_WORKSPACE_PROMPT" not in sys_content
    assert "# Specialist Soul Marker" in sys_content
    assert "I am the specialized scientific assistant." in sys_content
    assert "## Persona: Specialist Agent 🔬" in sys_content


def test_persona_direct_mode_preserves_archived_context_summary(env) -> None:
    from nanobot.coworker.agents.home import scaffold_agent_home

    agent = RoomAgentConfig(
        id="specialist",
        name="Specialist",
        home="agents/specialist",
    )
    scaffold_agent_home(env.workspace, agent)
    (env.workspace / "agents" / "specialist" / "SOUL.md").write_text(
        "# Specialist Soul", encoding="utf-8"
    )

    cfg = CoworkerConfig(room=RoomConfig(agents=[agent]))
    env.configure(cfg)
    env.bind()

    session = env.sessions.get_or_create(KEY)
    set_persona_id(session, "specialist", cfg)

    hook = CoworkerHook(
        AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    )
    agent_ctx = AgentHookContext(iteration=0, messages=[])

    archived_block = (
        "[Archived Context Summary]\n\n"
        "Previous conversation summary (last active 2026-10-05T10:00:00):\n"
        "- Discussed preliminary research objectives."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": f"ORIGINAL_PROMPT\n\n---\n\n{archived_block}"},
        {"role": "user", "content": "Continue research."},
    ]

    out_msgs, _ = hook.transform_request(agent_ctx, messages, None, stateful=False)
    sys_content = str(out_msgs[0]["content"])

    assert "# Specialist Soul" in sys_content
    assert "[Archived Context Summary]" in sys_content
    assert "Discussed preliminary research objectives." in sys_content


def test_persona_tool_policy_filtering(env) -> None:
    agent = RoomAgentConfig(
        id="analyst",
        name="Analyst",
        tools={"allow": ["read_file", "search*"], "deny": ["search_internal"]},
    )
    cfg = CoworkerConfig(room=RoomConfig(agents=[agent]))
    env.configure(cfg)
    env.bind()

    session = env.sessions.get_or_create(KEY)
    scheduler.set_armed(session, True)
    set_persona_id(session, "analyst", cfg)

    hook = CoworkerHook(
        AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    )
    agent_ctx = AgentHookContext(iteration=0, messages=[])

    tools = [
        {"function": {"name": "read_file"}},
        {"function": {"name": "search_web"}},
        {"function": {"name": "search_internal"}},
        {"function": {"name": "exec"}},
        {"function": {"name": "room_state"}},
    ]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "PROMPT"},
        {"role": "user", "content": "Analyze"},
    ]

    _, filtered_tools = hook.transform_request(agent_ctx, messages, tools, stateful=False)
    assert filtered_tools is not None
    tool_names = [t["function"]["name"] for t in filtered_tools]

    assert "read_file" in tool_names
    assert "search_web" in tool_names
    assert "room_state" in tool_names  # always-on
    assert "search_internal" not in tool_names  # denied
    assert "exec" not in tool_names  # not in allowlist


@pytest.mark.asyncio
async def test_persona_agent_notes_tool_in_direct_mode(env) -> None:
    from nanobot.agent.tools.context import RequestContext, request_context
    from nanobot.coworker.agents.home import scaffold_agent_home
    from nanobot.coworker.agents.notes_tool import AgentNotesTool

    agent = RoomAgentConfig(
        id="coach",
        name="Coach",
        home="agents/coach",
        memory="thread+notes",
    )
    scaffold_agent_home(env.workspace, agent)
    cfg = CoworkerConfig(room=RoomConfig(agents=[agent]))
    env.configure(cfg)
    env.bind()

    session = env.sessions.get_or_create(KEY)
    set_persona_id(session, "coach", cfg)

    # In transform_request with coach persona, agent_notes is NOT hidden
    hook = CoworkerHook(
        AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    )
    agent_ctx = AgentHookContext(iteration=0, messages=[])
    tools = [{"function": {"name": "agent_notes"}}, {"function": {"name": "read_file"}}]
    messages: list[dict[str, Any]] = [{"role": "system", "content": "P"}, {"role": "user", "content": "Q"}]

    _, filtered_tools = hook.transform_request(agent_ctx, messages, tools, stateful=False)
    assert filtered_tools is not None
    assert any(t["function"]["name"] == "agent_notes" for t in filtered_tools)

    # Calling agent_notes writes into coach's home/memory/MEMORY.md
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key=KEY)):
        tool = AgentNotesTool()
        res = await tool.execute(action="append", note="Stay consistent with routine")
        data = json.loads(res)
        assert data["status"] == "ok"

        mem_file = env.workspace / "agents" / "coach" / "memory" / "MEMORY.md"
        assert mem_file.is_file()
        assert "Stay consistent with routine" in mem_file.read_text(encoding="utf-8")


def test_persona_status_reports_mode_and_tools(env) -> None:
    from nanobot.coworker.agents.home import scaffold_agent_home

    agent_direct = RoomAgentConfig(
        id="direct_agent",
        name="Direct Agent",
        home="agents/direct_agent",
        tools={"allow": ["read_file", "search*"]},
    )
    agent_overlay = RoomAgentConfig(
        id="overlay_agent",
        name="Overlay Agent",
    )
    scaffold_agent_home(env.workspace, agent_direct)

    cfg = CoworkerConfig(room=RoomConfig(agents=[agent_direct, agent_overlay]))
    env.configure(cfg)
    env.bind()

    session = env.sessions.get_or_create(KEY)

    # Overlay mode when using overlay_agent
    set_persona_id(session, "overlay_agent", cfg)
    status_overlay = coworker_session_status(session)
    assert status_overlay["persona"] is not None
    assert status_overlay["persona"]["mode"] == "overlay"

    # Direct mode when using direct_agent
    set_persona_id(session, "direct_agent", cfg)
    status_direct = coworker_session_status(session)
    assert status_direct["persona"] is not None
    assert status_direct["persona"]["mode"] == "direct"


