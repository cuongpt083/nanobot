"""Tool allowing the agent to flag obsolete tool round-trips as wasted context."""

from __future__ import annotations

import json
from typing import Any

from nanobot.agent.inspector import get_inspector_store
from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.agent.tools.schema import (
    ArraySchema,
    IntegerSchema,
    StringSchema,
    tool_parameters_schema,
)


@tool_parameters(
    tool_parameters_schema(
        recent=IntegerSchema(
            description="Flag the N most recent tool round-trips in this conversation (e.g. 1 for the call you just made).",
            minimum=1,
            maximum=50,
        ),
        ids=ArraySchema(
            StringSchema("Explicit tool-call id"),
            description="Explicit tool-call ids to flag.",
        ),
        rescue_ids=ArraySchema(
            StringSchema("Explicit tool-call id to unmark"),
            description="Tool-call ids to un-mark / rescue back into context.",
        ),
        reason=StringSchema(
            "One short phrase: why it is dead weight (e.g. 'superseded search', 'dead-end run')."
        ),
    )
)
class MarkContextWastedTool(Tool):
    """Flag prior tool round-trips as dead weight to drop them from future context."""

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return True

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls()

    @property
    def name(self) -> str:
        return "mark_context_wasted"

    @property
    def description(self) -> str:
        return (
            "Flag prior tool calls in THIS conversation as wasted so they are dropped from "
            "future context (cheaper tokens, tighter focus): a dead-end search, an obsolete dump "
            "you already extracted what you need from, a step superseded by a later one. "
            "Do NOT flag anything you still need."
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self,
        recent: int | None = None,
        ids: list[str] | None = None,
        rescue_ids: list[str] | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> Any:
        req = current_request_context()
        session_key = req.session_key if req else None
        if not session_key:
            return ToolResult.error("No active session key available.")

        store = get_inspector_store(req.workspace if req else None)
        out = store.mark_wasted(
            session_key=session_key,
            recent=recent,
            ids=ids,
            rescue_ids=rescue_ids,
            reason=reason,
        )
        return json.dumps(out, ensure_ascii=False)
