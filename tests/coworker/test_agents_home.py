"""Tests for coworker AgentHome scaffolding and /agent commands (Phase 1.3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.coworker.agents.home import agent_home_path, init_agent, scaffold_agent_home
from nanobot.coworker.commands import cmd_agent, register
from nanobot.coworker.config import (
    RoomAgentConfig,
    invalidate_coworker_config_cache,
    load_coworker_config,
    set_coworker_config_override,
)
from nanobot.coworker.runtime import CoworkerServices


@pytest.fixture
def test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg_file = tmp_path / "coworker.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("NANOBOT_COWORKER_CONFIG", str(cfg_file))
    set_coworker_config_override(None)
    invalidate_coworker_config_cache()
    yield cfg_file, workspace
    invalidate_coworker_config_cache()


def test_scaffold_agent_home_creates_files_and_idempotent(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    agent = RoomAgentConfig(
        id="nutri-coach",
        name="Nutri Coach",
        bio="Clinical dietitian and nutrition expert.",
        instructions="Always check BMI and caloric needs.",
    )

    # 1. First run
    res = scaffold_agent_home(workspace, agent)
    home_dir = workspace / "agents" / "nutri-coach"
    assert res["home"] == "agents/nutri-coach"
    assert "SOUL.md" in res["created_files"]
    assert "memory/MEMORY.md" in res["created_files"]
    assert not res["skipped_files"]

    soul = (home_dir / "SOUL.md").read_text(encoding="utf-8")
    assert "Nutri Coach (nutri-coach)" in soul
    assert "Clinical dietitian" in soul
    assert "Always check BMI" in soul

    memory = (home_dir / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    assert "Memory for Nutri Coach" in memory

    assert (home_dir / "skills").is_dir()

    # 2. Second run without changes does not overwrite
    (home_dir / "SOUL.md").write_text("Custom customized soul", encoding="utf-8")
    res2 = scaffold_agent_home(workspace, agent)
    assert not res2["created_files"]
    assert "SOUL.md" in res2["skipped_files"]
    assert "memory/MEMORY.md" in res2["skipped_files"]
    assert (home_dir / "SOUL.md").read_text(encoding="utf-8") == "Custom customized soul"


def test_init_agent_updates_config(test_env: tuple[Path, Path]) -> None:
    cfg_file, workspace = test_env
    cfg_file.write_text(
        json.dumps({
            "room": {
                "agents": [
                    {
                        "id": "researcher",
                        "name": "Researcher",
                        "bio": "Fact checker and analyst.",
                        "instructions": "Be accurate.",
                    }
                ]
            }
        }),
        encoding="utf-8",
    )

    res = init_agent(workspace, "researcher")
    assert res["home"] == "agents/researcher"

    # Verify config was updated with home
    cfg = load_coworker_config()
    assert cfg.room.agents[0].home == "agents/researcher"

    # Agent path
    hp = agent_home_path(workspace, cfg.room.agents[0])
    assert hp is not None
    assert hp == (workspace / "agents" / "researcher").resolve()


def test_init_agent_missing_raises(test_env: tuple[Path, Path]) -> None:
    cfg_file, workspace = test_env
    cfg_file.write_text(json.dumps({"room": {"agents": []}}), encoding="utf-8")
    with pytest.raises(ValueError, match="not found in room.agents"):
        init_agent(workspace, "unknown")


@pytest.mark.asyncio
async def test_cmd_agent_list_init_show(test_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file, workspace = test_env
    cfg_file.write_text(
        json.dumps({
            "room": {
                "agents": [
                    {
                        "id": "helper",
                        "name": "Helpful Agent",
                        "bio": "General assistant",
                        "instructions": "Help people.",
                    }
                ]
            }
        }),
        encoding="utf-8",
    )

    # Bind services safely via monkeypatch
    mock_services = CoworkerServices(
        workspace=workspace,
        bus=MagicMock(),
        sessions=MagicMock(),
        subagents=MagicMock(),
        provider_snapshot_loader=MagicMock(),
    )
    monkeypatch.setattr("nanobot.coworker.runtime._services", mock_services)

    def make_ctx(args: str) -> CommandContext:
        raw_cmd = f"/agent {args}"
        msg = InboundMessage(channel="system", chat_id="user1", content=raw_cmd, sender_id="u1")
        return CommandContext(
            msg=msg,
            raw=raw_cmd,
            key="system:user1",
            args=args,
            loop=MagicMock(),
            session=MagicMock(),
        )

    # 1. /agent list before init
    resp = await cmd_agent(make_ctx("list"))
    assert "Configured room agents" in resp.content
    assert "helper" in resp.content
    assert "none" in resp.content

    # 2. /agent init helper
    resp_init = await cmd_agent(make_ctx("init helper"))
    assert "Agent `helper` home initialized" in resp_init.content
    assert "Created: SOUL.md, memory/MEMORY.md" in resp_init.content

    # 3. /agent list after init
    resp_list2 = await cmd_agent(make_ctx("list"))
    assert "(exists)" in resp_list2.content

    # 4. /agent show helper
    resp_show = await cmd_agent(make_ctx("show helper"))
    assert "Agent:** `helper`" in resp_show.content
    assert "Help people." in resp_show.content

    # 5. /agent show non-existent
    resp_show_missing = await cmd_agent(make_ctx("show nonexistent"))
    assert "not found" in resp_show_missing.content


def test_agent_command_registered_in_router() -> None:
    router = CommandRouter()
    register(router)
    assert router.is_dispatchable_command("/agent")
    assert router.is_dispatchable_command("/agent list")
