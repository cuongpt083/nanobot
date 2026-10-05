"""Tool construction and policy for coworker agents."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.agent.tools.file_state import FileStates
from nanobot.agent.tools.loader import ToolLoader
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.config.schema import ToolsConfig
from nanobot.security.workspace_access import workspace_sandbox_status

if TYPE_CHECKING:
    from nanobot.coworker.config import RoomAgentConfig
    from nanobot.coworker.runtime import CoworkerServices


def build_tools(
    agent: RoomAgentConfig,
    svc: CoworkerServices,
    *,
    project_root: Path,
    exec_session_manager: ExecSessionManager | None = None,
) -> ToolRegistry:
    """Build isolated subagent toolset for a coworker agent."""
    registry = ToolRegistry()
    ctx = subagent_tool_context(
        svc,
        project_root,
        exec_session_manager=exec_session_manager,
    )
    ToolLoader().load(ctx, registry, scope="subagent")
    return registry


def subagent_tool_context(
    svc: CoworkerServices,
    project_root: Path,
    tools_config: ToolsConfig | None = None,
    exec_session_manager: ExecSessionManager | None = None,
) -> ToolContext:
    root = project_root.resolve()
    base_cfg = tools_config or svc.tools_config or ToolsConfig()
    cfg = ToolsConfig(
        exec=base_cfg.exec,
        web=base_cfg.web,
        file=base_cfg.file,
        restrict_to_workspace=base_cfg.restrict_to_workspace,
    )
    sandbox = (
        svc.workspace_sandbox
        if svc.workspace_sandbox is not None
        else workspace_sandbox_status(
            restrict_to_workspace=cfg.restrict_to_workspace,
            workspace=root,
        )
    )
    esm = exec_session_manager if exec_session_manager is not None else ExecSessionManager()
    # Do not pass bus/sessions/subagent_manager: CoworkerTool.create() would
    # rebind process-wide services to this guest context.
    return ToolContext(
        config=cfg,
        workspace=str(root),
        exec_session_manager=esm,
        file_state_store=FileStates(),
        workspace_sandbox=sandbox,
        timezone=svc.timezone,
    )

