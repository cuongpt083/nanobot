"""Shared plumbing for coworker tools."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.context import current_request_context
from nanobot.coworker.runtime import bind_services, get_session

if TYPE_CHECKING:
    from nanobot.agent.tools.context import RequestContext, ToolContext
    from nanobot.session.manager import Session


class CoworkerTool(Tool):
    """Base: binds loop services on creation and exposes request helpers.

    Abstract, so the tool loader skips it; concrete subclasses are discovered
    through the ``nanobot/agent/tools/coworker.py`` shim.
    """

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        bind_services(ctx)
        return cls()

    @staticmethod
    def request() -> RequestContext | None:
        return current_request_context()

    @staticmethod
    def session() -> Session | None:
        ctx = current_request_context()
        return get_session(ctx.session_key) if ctx is not None else None

    @staticmethod
    def payload(status: str, **fields: Any) -> ToolResult:
        text = json.dumps({"status": status, **fields}, ensure_ascii=False, indent=2)
        return ToolResult.error(text) if status == "error" else ToolResult(text)
