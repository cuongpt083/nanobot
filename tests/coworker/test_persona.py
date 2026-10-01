"""Tests for per-session persona support."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.hook import CoworkerHook
from nanobot.coworker.persona import get_persona_id, resolve_persona, set_persona_id
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
