"""Persistent notes tool for coworker agents with memory='thread+notes'."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any, Literal

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker.agents.home import agent_home_path
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.room.scheduler import current_room_actor
from nanobot.coworker.runtime import services
from nanobot.coworker.tools_base import CoworkerTool

if TYPE_CHECKING:
    from nanobot.agent.tools.context import ToolContext

MAX_NOTE_CHARS = 500
MAX_FILE_BYTES = 32 * 1024  # 32 KB


@tool_parameters({
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["append", "list"],
            "description": "Action to perform: 'append' to save a note, 'list' to view existing notes.",
        },
        "note": {
            "type": "string",
            "description": "The lesson or note to record (max 500 characters). Required for 'append'.",
        },
    },
    "required": ["action"],
})
class AgentNotesTool(CoworkerTool):
    """View and record durable lessons into the agent's private memory/MEMORY.md."""

    _scopes = {"subagent"}

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        actor = current_room_actor.get()
        if actor is None:
            return False
        cfg = load_coworker_config()
        agent = cfg.agent(actor.agent_id)
        return agent is not None and agent.memory == "thread+notes"

    @property
    def name(self) -> str:
        return "agent_notes"

    @property
    def description(self) -> str:
        return (
            "Append or list durable lessons learned in your private memory. "
            "Only available for teammates configured with 'thread+notes' memory."
        )

    async def execute(
        self,
        action: Literal["append", "list"] = "list",
        note: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        actor = current_room_actor.get()
        if actor is None:
            return self.payload("error", error="agent_notes is only available during an active room turn.")

        svc = services()
        if svc is None:
            return self.payload("error", error="Coworker services are not available.")

        cfg = load_coworker_config()
        agent = cfg.agent(actor.agent_id)
        if agent is None:
            return self.payload("error", error=f"Agent '{actor.agent_id}' not found in configuration.")

        if agent.memory != "thread+notes":
            return self.payload("error", error=f"Agent '{actor.agent_id}' does not have memory='thread+notes' enabled.")

        home = agent_home_path(svc.workspace, agent)
        if home is None or not home.is_dir():
            return self.payload("error", error=f"Agent home directory for '{actor.agent_id}' is not initialized.")

        mem_dir = home / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        mem_file = mem_dir / "MEMORY.md"

        if action == "list":
            if not mem_file.is_file():
                return self.payload("ok", notes="", message="No notes recorded yet.")
            try:
                content = mem_file.read_text(encoding="utf-8")
                return self.payload("ok", notes=content)
            except OSError as exc:
                return self.payload("error", error=f"Failed to read memory file: {exc}")

        if action == "append":
            if not note or not note.strip():
                return self.payload("error", error="Note cannot be empty for 'append' action.")

            clean_note = note.strip()
            if len(clean_note) > MAX_NOTE_CHARS:
                return self.payload(
                    "error",
                    error=f"Note exceeds maximum length of {MAX_NOTE_CHARS} characters (got {len(clean_note)}).",
                )

            current_size = mem_file.stat().st_size if mem_file.is_file() else 0
            date_prefix = datetime.date.today().isoformat()
            entry_line = f"- [{date_prefix}] {clean_note}\n"
            entry_bytes = len(entry_line.encode("utf-8"))

            if current_size + entry_bytes > MAX_FILE_BYTES:
                return self.payload(
                    "error",
                    error=f"Memory file would exceed maximum size of {MAX_FILE_BYTES} bytes. Note rejected.",
                )

            try:
                with mem_file.open("a", encoding="utf-8") as fh:
                    fh.write(entry_line)
                return self.payload("ok", recorded=clean_note)
            except OSError as exc:
                return self.payload("error", error=f"Failed to write note: {exc}")

        return self.payload("error", error=f"Unknown action '{action}'.")
