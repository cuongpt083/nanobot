"""``file_write_staged`` — propose a file write for the user to review (Phase 8)."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.persona import get_persona_id
from nanobot.coworker.tools_base import CoworkerTool

STAGED_TOOL = "file_write_staged"


@tool_parameters({
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Project-relative path of the file to change."},
        "content": {"type": "string", "description": "The complete new content of the file."},
        "base_version": {
            "type": "string",
            "description": (
                "The version you read the file at (from read_file or the last proposal). Required when the "
                "file exists; omit only to create a new file."
            ),
        },
    },
    "required": ["path", "content"],
})
class FileWriteStagedTool(CoworkerTool):
    @property
    def name(self) -> str:
        return STAGED_TOOL

    @property
    def description(self) -> str:
        return (
            "Propose a change to a project file. The user reviews it in the editor and accepts or rejects it; "
            "nothing is written until they accept. Use it for any file outside .coworker/drafts/."
        )

    @property
    def read_only(self) -> bool:
        return False

    async def execute(
        self,
        path: str = "",
        content: Any = None,
        base_version: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        from nanobot.coworker.advisor.tool import project_root_for
        from nanobot.coworker.staged import store

        request = self.request()
        session = self.session()
        if request is None or session is None:
            return self.payload("error", error="no active session")
        if not load_coworker_config().staging.enabled:
            return self.payload("error", error="staged writes are not enabled for this project")
        root = project_root_for(session)
        if root is None:
            return self.payload("error", error="no project directory for this session")
        persona = get_persona_id(session)
        try:
            record = store.propose(
                root,
                path=path,
                content=content,
                base_version=base_version,
                by=persona or "coordinator",
                session_key=request.session_key,
            )
        except store.ProposalError as e:
            return self.payload("error", error=e.message, status_code=e.status, **e.details)
        return self.payload(
            "staged",
            id=record["id"],
            path=record["path"],
            note="Proposed. The user reviews it in the editor; the file is unchanged until they accept.",
        )
