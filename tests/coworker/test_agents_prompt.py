from pathlib import Path

from nanobot.coworker.agents.home import scaffold_agent_home
from nanobot.coworker.agents.prompt import (
    build_system_prompt,
    inherited_skills_summary,
    legacy_prompt,
    resolve_home,
)
from nanobot.coworker.config import RoomAgentConfig
from nanobot.coworker.runtime import CoworkerServices


def test_resolve_home(tmp_path: Path):
    agent_no_home = RoomAgentConfig(id="agent1")
    assert resolve_home(agent_no_home, tmp_path) is None

    agent_with_home = RoomAgentConfig(id="agent2", home="agents/agent2")
    assert resolve_home(agent_with_home, tmp_path) is None

    # After scaffolding
    scaffold_agent_home(tmp_path, agent_with_home)
    assert resolve_home(agent_with_home, tmp_path) == (tmp_path / "agents/agent2").resolve()


def test_legacy_prompt(tmp_path: Path):
    agent = RoomAgentConfig(id="helper", bio="helpful agent", instructions="Do things well")
    roster = [agent]
    prompt = legacy_prompt(agent, tmp_path, roster)
    assert "You are agent \"helper\"" in prompt
    assert "Do things well" in prompt
    assert "SHARED STATE IS MANDATORY" in prompt


def test_build_system_prompt_home_vs_legacy(tmp_path: Path):
    agent = RoomAgentConfig(
        id="specialist",
        name="Dr Specialist",
        home="agents/specialist",
        instructions="Ignore this for SOUL",
        memory="thread+notes",
    )
    roster = [agent]
    svc = CoworkerServices(
        workspace=tmp_path,
        bus=None,  # type: ignore
        sessions=None,  # type: ignore
        subagents=None,
        provider_snapshot_loader=None,
    )

    # Before home exists -> legacy prompt
    prompt_legacy = build_system_prompt(agent, project_root=tmp_path, svc=svc, roster=roster)
    assert "You are agent \"Dr Specialist\"" in prompt_legacy

    # Scaffold home and customize SOUL.md and AGENTS.md
    scaffold_agent_home(tmp_path, agent)
    home_dir = tmp_path / "agents/specialist"
    (home_dir / "SOUL.md").write_text("# Specialist Soul\nI am the specialist.", encoding="utf-8")
    (home_dir / "memory" / "MEMORY.md").write_text("- Specialist learned trick 1", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Project Guide\nFollow rules.", encoding="utf-8")

    prompt_home = build_system_prompt(agent, project_root=tmp_path, svc=svc, roster=roster)
    assert "Specialist Soul" in prompt_home
    assert "Specialist learned trick 1" in prompt_home
    assert "Project Guide" in prompt_home
    assert "## Multi-agent room member" in prompt_home
    assert "You are collaborating in a multi-agent room coordinated by the room coordinator." in prompt_home


def test_inherited_skills(tmp_path: Path):
    # Create a workspace skill
    skill_dir = tmp_path / "skills" / "custom-math"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: custom-math\ndescription: Solve math\n---\nMath instructions",
        encoding="utf-8",
    )

    summary_empty = inherited_skills_summary(tmp_path, [])
    assert summary_empty == ""

    summary = inherited_skills_summary(tmp_path, ["custom-math"])
    assert "custom-math" in summary
    assert "Solve math" in summary
