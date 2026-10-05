"""Tool construction and policy for coworker agents."""

from __future__ import annotations

import fnmatch
import re
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
    from nanobot.coworker.config import NamePolicy, RoomAgentConfig
    from nanobot.coworker.runtime import CoworkerServices

ALWAYS_ON_TOOLS = frozenset({"agents_list", "room_delegate", "room_state", "agent_notes"})
_SANITIZE_RE = re.compile(r"_+")

# Names hashed past 64 chars only match through a `*` tail (see `_limit_tool_name`).


def _sanitize_mcp_segment(name: str) -> str:
    """Match MCP wrapper naming: non [A-Za-z0-9_-] → `_`, collapse runs."""
    return _SANITIZE_RE.sub("_", re.sub(r"[^a-zA-Z0-9_-]", "_", name))


def mcp_server_from_allow_pattern(pattern: str) -> str | None:
    """Extract a stable MCP server label from an allow pattern, if any."""
    raw = pattern.strip()
    if raw.startswith("mcp:"):
        rest = raw[4:]
        if rest in ("", "*"):
            return None
        server, sep, _tool = rest.partition(":")
        if not sep:
            server = rest
        if server in ("", "*"):
            return None
        return _sanitize_mcp_segment(server)
    if raw.startswith("mcp_"):
        server, _sep, _rest = raw[4:].partition("_")
        server = server.rstrip("*?[]")
        return server or None
    return None


def pattern_to_glob(pattern: str) -> str:
    """Translate an allow/deny pattern into a glob over the registered tool name.

    ``mcp:<server>:<pat>`` and ``mcp_<server>_<pat>`` both map onto the sanitized
    ``mcp_<server>_<tool>`` name used by MCP wrappers.
    """
    raw = pattern.strip()
    if raw.startswith("mcp:"):
        rest = raw[4:]
        if rest in ("", "*"):
            return "mcp_*"
        server, sep, tool_pat = rest.partition(":")
        if not sep:
            return f"mcp_{_sanitize_mcp_segment(rest)}*"
        server_part = "*" if server in ("", "*") else _sanitize_mcp_segment(server)
        tool_part = "*" if tool_pat in ("", "*") else tool_pat
        return f"mcp_{server_part}_{tool_part}"
    return raw


def matches_tool_name(name: str, pattern: str) -> bool:
    """Return whether ``name`` matches one allow/deny pattern (case-sensitive glob)."""
    return fnmatch.fnmatchcase(name, pattern_to_glob(pattern))


def matches_any(name: str, patterns: list[str]) -> bool:
    return any(matches_tool_name(name, pattern) for pattern in patterns)


def apply_policy(
    registry: ToolRegistry,
    policy: NamePolicy,
    *,
    always: frozenset[str] = ALWAYS_ON_TOOLS,
) -> ToolRegistry:
    """Filter ``registry`` in place. Empty allow keeps the current set; deny always wins."""
    names = list(registry.tool_names)
    if policy.allow:
        keep = {name for name in names if name in always or matches_any(name, policy.allow)}
        for name in names:
            if name not in keep:
                registry.unregister(name)
        names = list(registry.tool_names)
    if policy.deny:
        for name in names:
            if matches_any(name, policy.deny):
                registry.unregister(name)
    return registry


def build_tools(
    agent: RoomAgentConfig,
    svc: CoworkerServices,
    *,
    project_root: Path,
    exec_session_manager: ExecSessionManager | None = None,
    restrict_to_workspace: bool | None = None,
) -> ToolRegistry:
    """Build an isolated subagent toolset, optionally borrowing MCP wrappers from the main loop."""
    registry = ToolRegistry()
    ctx = subagent_tool_context(
        svc,
        project_root,
        exec_session_manager=exec_session_manager,
        restrict_to_workspace=restrict_to_workspace,
    )
    ToolLoader().load(ctx, registry, scope="subagent")
    if svc.main_tools is not None and agent.tools.allow:
        for name in svc.main_tools.tool_names:
            if not name.startswith("mcp_"):
                continue
            if not matches_any(name, agent.tools.allow):
                continue
            tool = svc.main_tools.get(name)
            if tool is not None:
                # Share the live wrapper so reconnect refreshes `_session` for guests too.
                registry.register(tool)
    return apply_policy(registry, agent.tools, always=ALWAYS_ON_TOOLS)


def subagent_tool_context(
    svc: CoworkerServices,
    project_root: Path,
    tools_config: ToolsConfig | None = None,
    exec_session_manager: ExecSessionManager | None = None,
    restrict_to_workspace: bool | None = None,
) -> ToolContext:
    root = project_root.resolve()
    base_cfg = tools_config or svc.tools_config or ToolsConfig()
    restrict = (
        restrict_to_workspace
        if restrict_to_workspace is not None
        else base_cfg.restrict_to_workspace
    )
    cfg = ToolsConfig(
        exec=base_cfg.exec,
        web=base_cfg.web,
        file=base_cfg.file,
        restrict_to_workspace=restrict,
    )
    sandbox = workspace_sandbox_status(
        restrict_to_workspace=cfg.restrict_to_workspace,
        workspace=root,
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
