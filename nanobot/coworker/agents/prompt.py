"""System prompt generation for coworker agents."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nanobot.agent.context import ContextBuilder
from nanobot.agent.skills import SkillsLoader
from nanobot.coworker import directives
from nanobot.coworker.agents.home import agent_home_path

if TYPE_CHECKING:
    from nanobot.coworker.config import RoomAgentConfig
    from nanobot.coworker.runtime import CoworkerServices


def resolve_home(agent: RoomAgentConfig, workspace: Path) -> Path | None:
    """Return the absolute path to agent home if configured and existing, else None."""
    p = agent_home_path(workspace, agent)
    if p is not None and p.is_dir():
        return p
    return None


def legacy_prompt(
    agent: RoomAgentConfig,
    project_root: Path,
    roster: list[RoomAgentConfig],
) -> str:
    """Build the legacy system prompt for agents without an initialized home.

    Mirrors subagent system prompt template + directives.room_guest.
    """
    from nanobot.utils.prompt_templates import render_template

    agent_workspace = project_root.expanduser().resolve()
    base_subagent = render_template(
        "agent/subagent_system.md",
        workspace=str(agent_workspace),
        agent_workspace=str(agent_workspace),
        history_log="memory/history.jsonl",
        skills_summary="",
    )
    guest_directive = directives.room_guest(agent, "the room coordinator", roster)
    return f"{base_subagent}\n\n---\n\n{guest_directive}"


def inherited_skills_summary(workspace: Path, inherit: list[str]) -> str:
    """Build a skills summary markdown block for inherited skills from workspace."""
    if not inherit:
        return ""
    loader = SkillsLoader(workspace)
    all_skills = loader.list_skills(filter_unavailable=False)
    inherit_set = set(inherit)
    # exclude everything not in inherit
    exclude = {s["name"] for s in all_skills if s["name"] not in inherit_set}
    summary = loader.build_skills_summary(exclude=exclude, workspace=workspace)
    if not summary:
        return ""
    from nanobot.utils.prompt_templates import render_template

    return render_template("agent/skills_section.md", skills_summary=summary)


def build_system_prompt(
    agent: RoomAgentConfig,
    *,
    project_root: Path,
    svc: CoworkerServices,
    roster: list[RoomAgentConfig],
) -> str:
    home = resolve_home(agent, svc.workspace)
    if home is None:
        return legacy_prompt(agent, project_root, roster)

    disabled_skills = list(agent.skills.deny) if agent.skills.deny else None
    builder = ContextBuilder(home, timezone=svc.timezone, disabled_skills=disabled_skills)
    base = builder.build_system_prompt(
        workspace=project_root,
        include_memory=agent.memory == "thread+notes",
    )
    parts = [base]
    if agent.skills.inherit:
        summary = inherited_skills_summary(svc.workspace, agent.skills.inherit)
        if summary:
            parts.append(summary)
    parts.append(directives.room_member(agent, roster))
    return "\n\n---\n\n".join(p for p in parts if p)
