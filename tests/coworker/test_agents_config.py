"""Tests for coworker RoomAgentConfig and RoomConfig schema enhancements (Phase 1.1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig


def test_room_agent_config_defaults() -> None:
    agent = RoomAgentConfig(id="nutri-coach")
    assert agent.id == "nutri-coach"
    assert agent.home is None
    assert agent.tools.allow == []
    assert agent.tools.deny == []
    assert agent.skills.inherit == []
    assert agent.skills.deny == []
    assert agent.memory == "thread"
    assert agent.thread_turns == 8
    assert agent.max_iterations == 40
    assert agent.output_contract == "default"


def test_room_config_defaults() -> None:
    room = RoomConfig()
    assert room.max_parallel == 3
    assert room.context_turns == 5
    assert room.min_context_chars == 80
    assert room.legacy_guest_runner is False


def test_room_agent_camel_case_parsing() -> None:
    data = {
        "id": "helper",
        "home": "agents/helper",
        "tools": {"allow": ["read_file", "search*"], "deny": ["exec*"]},
        "skills": {"inherit": ["cron"], "deny": ["weather"]},
        "memory": "thread+notes",
        "threadTurns": 12,
        "maxIterations": 50,
        "outputContract": "none",
    }
    agent = RoomAgentConfig.model_validate(data)
    assert agent.home == "agents/helper"
    assert agent.tools.allow == ["read_file", "search*"]
    assert agent.tools.deny == ["exec*"]
    assert agent.skills.inherit == ["cron"]
    assert agent.skills.deny == ["weather"]
    assert agent.memory == "thread+notes"
    assert agent.thread_turns == 12
    assert agent.max_iterations == 50
    assert agent.output_contract == "none"


def test_room_agent_home_validation_relative_and_no_dotdot() -> None:
    # Valid relative paths
    a1 = RoomAgentConfig(id="a1", home="agents/sub")
    assert a1.home == "agents/sub"

    a2 = RoomAgentConfig(id="a2", home="my_agent")
    assert a2.home == "my_agent"

    # Invalid: dotdot
    with pytest.raises(ValidationError, match="relative path and cannot contain '\\.\\.'"):
        RoomAgentConfig(id="bad1", home="../agents/bad")

    with pytest.raises(ValidationError, match="relative path and cannot contain '\\.\\.'"):
        RoomAgentConfig(id="bad2", home="agents/../../bad")

    # Invalid: absolute Unix
    with pytest.raises(ValidationError, match="relative path and cannot contain '\\.\\.'"):
        RoomAgentConfig(id="bad3", home="/etc/agents")

    # Invalid: absolute Windows / drive
    with pytest.raises(ValidationError):
        RoomAgentConfig(id="bad4", home="C:\\agents")

    # Invalid: Windows UNC or leading backslash
    with pytest.raises(ValidationError):
        RoomAgentConfig(id="bad5", home="\\\\server\\share\\agents")

    with pytest.raises(ValidationError):
        RoomAgentConfig(id="bad6", home="\\agents\\sub")


def test_room_agent_backend_and_home_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="backend and home cannot be specified together"):
        RoomAgentConfig(id="coder", backend="pi", home="agents/coder")


def test_coworker_config_roundtrip_with_agent_extensions() -> None:
    raw = {
        "room": {
            "maxParallel": 4,
            "contextTurns": 6,
            "minContextChars": 100,
            "agents": [
                {
                    "id": "researcher",
                    "home": "agents/researcher",
                    "tools": {"allow": ["web_search", "web_fetch"]},
                }
            ],
        }
    }
    cfg = CoworkerConfig.model_validate(raw)
    assert cfg.room.max_parallel == 4
    assert cfg.room.context_turns == 6
    assert cfg.room.min_context_chars == 100
    assert len(cfg.room.agents) == 1
    assert cfg.room.agents[0].id == "researcher"
    assert cfg.room.agents[0].home == "agents/researcher"
    assert cfg.room.agents[0].tools.allow == ["web_search", "web_fetch"]
