"""AgentHome management and scaffolding for Coworker teammates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.coworker.config import RoomAgentConfig, load_coworker_config
from nanobot.coworker.settings_api import update_coworker_settings


def agent_home_path(workspace: Path, agent: RoomAgentConfig) -> Path | None:
    """Return the absolute Path to the agent's home directory if configured."""
    if not agent.home:
        return None
    return (workspace / agent.home).resolve()


def scaffold_agent_home(workspace: Path, agent: RoomAgentConfig) -> dict[str, Any]:
    """Scaffold an agent home directory if it does not already exist.

    Directory structure:
    <workspace>/agents/<id>/
      SOUL.md            # role, voice, principles; generated from bio + instructions
      USER.md            # optional; initially empty template
      memory/MEMORY.md   # persistent notes
      skills/

    Does not overwrite existing files.
    """
    rel_home = agent.home or f"agents/{agent.id}"
    home_dir = (workspace / rel_home).resolve()

    created_files: list[str] = []
    skipped_files: list[str] = []

    home_dir.mkdir(parents=True, exist_ok=True)
    (home_dir / "memory").mkdir(parents=True, exist_ok=True)
    (home_dir / "skills").mkdir(parents=True, exist_ok=True)

    soul_file = home_dir / "SOUL.md"
    if not soul_file.exists():
        soul_content = (
            f"# {agent.name or agent.id} ({agent.id})\n\n"
            f"{agent.bio or 'Specialized coworker teammate.'}\n\n"
            f"## Instructions\n\n"
            f"{agent.instructions or 'Follow directives and provide expert assistance in your domain.'}\n"
        )
        soul_file.write_text(soul_content, encoding="utf-8")
        created_files.append("SOUL.md")
    else:
        skipped_files.append("SOUL.md")

    memory_file = home_dir / "memory" / "MEMORY.md"
    if not memory_file.exists():
        mem_content = f"# Memory for {agent.name or agent.id}\n\nPersistent notes and domain context.\n"
        memory_file.write_text(mem_content, encoding="utf-8")
        created_files.append("memory/MEMORY.md")
    else:
        skipped_files.append("memory/MEMORY.md")

    return {
        "home": rel_home,
        "full_path": str(home_dir),
        "created_files": created_files,
        "skipped_files": skipped_files,
    }


def init_agent(workspace: Path, agent_id: str, preset_names: list[str] | None = None) -> dict[str, Any]:
    """Initialize agent home for a room agent, and update coworker.json if home wasn't set."""
    cfg = load_coworker_config()
    target_agent: RoomAgentConfig | None = None
    for a in cfg.room.agents:
        if a.id == agent_id:
            target_agent = a
            break

    if target_agent is None:
        raise ValueError(f"Agent {agent_id!r} not found in room.agents")

    rel_home = target_agent.home or f"agents/{agent_id}"
    res = scaffold_agent_home(workspace, target_agent)

    # If home was not set in coworker config, persist it
    if not target_agent.home:
        agents_data: list[dict[str, Any]] = []
        all_presets: set[str] = {"default"}
        if preset_names:
            all_presets.update(preset_names)
        for a in cfg.room.agents:
            adump = a.model_dump(mode="json", by_alias=True)
            if a.preset:
                all_presets.add(a.preset)
            if a.id == agent_id:
                adump["home"] = rel_home
            agents_data.append(adump)

        update_coworker_settings(
            {"room": {"agents": agents_data}},
            all_presets,
            detect=False,
            workspace=workspace,
        )

    return res
