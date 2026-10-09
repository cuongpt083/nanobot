"""Discovery shim: exposes the coworker extension's tools to ``ToolLoader``.

The tools live in ``nanobot.coworker``; importing them here lets the built-in
pkgutil scan register them without touching upstream loader code.
"""

from nanobot.coworker.advisor.tool import AdvisorTool
from nanobot.coworker.agents.notes_tool import AgentNotesTool
from nanobot.coworker.coding.tools import CodingAgentTool
from nanobot.coworker.context.tools import MarkContextWastedTool
from nanobot.coworker.room.tools import AgentsListTool, RoomDelegateTool, RoomStateTool
from nanobot.coworker.staged.tools import FileWriteStagedTool
from nanobot.coworker.workflows.tools import WorkflowDistillTool, WorkflowRunTool

__all__ = [
    "AdvisorTool",
    "AgentNotesTool",
    "AgentsListTool",
    "CodingAgentTool",
    "FileWriteStagedTool",
    "MarkContextWastedTool",
    "RoomDelegateTool",
    "RoomStateTool",
    "WorkflowDistillTool",
    "WorkflowRunTool",
]
