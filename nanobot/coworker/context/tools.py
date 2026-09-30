"""``mark_context_wasted`` — the agent flags dead-weight tool round-trips.

Marks are tool-call ids stored in the session (persisted). The optimizer drops
the matching call/result pairs from future payloads — adopted only when the
prompt cache is cold, so a mark never busts a warm cache.
"""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from typing import Any

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker.runtime import live_messages, session_state
from nanobot.coworker.tools_base import CoworkerTool
from nanobot.coworker.transcript import as_list, tool_call_name, tool_calls

WASTED_TOOL = "mark_context_wasted"
MAX_WASTED = 500


def wasted_ids(session: Any) -> frozenset[str]:
    return frozenset(str(i) for i in as_list(session_state(session).get("wasted_ids")) or [])


@tool_parameters({
    "type": "object",
    "properties": {
        "recent": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "description": "Flag the N most recent tool round-trips (e.g. 1 for the call you just made).",
        },
        "ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Explicit tool-call ids to flag.",
        },
        "reason": {"type": "string", "description": "One short phrase: why it is dead weight."},
    },
})
class MarkContextWastedTool(CoworkerTool):
    @property
    def name(self) -> str:
        return WASTED_TOOL

    @property
    def description(self) -> str:
        return (
            "Flag prior tool calls in THIS conversation as wasted so they are dropped from future context "
            "(cheaper tokens, tighter focus): a dead-end search, an obsolete dump you already extracted what "
            "you need from, a step superseded by a later one. Do NOT flag anything you still need."
        )

    async def execute(
        self,
        recent: int | None = None,
        ids: list[str] | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        request = self.request()
        session = self.session()
        if request is None or session is None:
            return self.payload("error", error="no active session")
        chosen: list[str] = [str(i) for i in (ids or []) if str(i).strip()]
        if recent:
            history = live_messages(request.session_key) or session.messages
            candidates = [
                str(call.get("id"))
                for m in history
                for call in tool_calls(m)
                if call.get("id") and tool_call_name(call) != WASTED_TOOL
            ]
            chosen += candidates[-recent:]
        if not chosen:
            return self.payload("error", error="nothing to flag — pass `recent` or `ids`.")
        state = session_state(session)
        existing = [i for i in as_list(state.get("wasted_ids")) or [] if isinstance(i, str)]
        merged = list(dict.fromkeys([*existing, *chosen]))[-MAX_WASTED:]
        state["wasted_ids"] = merged
        return self.payload(
            "ok",
            flagged=len(set(chosen) - set(existing)),
            total=len(merged),
            note="Dropped from future context once the prompt cache is idle (never mid-warm).",
        )
