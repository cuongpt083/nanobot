"""Room tools: ``agents_list``, ``room_delegate``, ``room_state``.

Registered for the coordinator (core scope) and for teammates (subagent scope,
only while a room guest turn runs). Outside an armed room the coworker hook
hides them from the model, so plain chats pay no token cost.
"""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.room import scheduler
from nanobot.coworker.room.store import RoomStateStore, room_id_for
from nanobot.coworker.runtime import services
from nanobot.coworker.tools_base import CoworkerTool

if TYPE_CHECKING:
    from nanobot.agent.tools.context import ToolContext

ROOM_TOOLS = frozenset({"agents_list", "room_delegate", "room_state"})


class _RoomTool(CoworkerTool):
    _scopes = {"core", "subagent"}

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        # Main loop: always (hidden per session by the hook). Subagents: only room guests.
        return ctx.bus is not None or scheduler.current_room_actor.get() is not None

    def _identity(self) -> tuple[str, str] | None:
        """(room session key, acting agent id) for the current call."""
        actor = scheduler.current_room_actor.get()
        if actor is not None:
            return actor.session_key, actor.agent_id
        request = self.request()
        if request is None or not request.session_key:
            return None
        return request.session_key, "owner"


class AgentsListTool(_RoomTool):
    @property
    def name(self) -> str:
        return "agents_list"

    @property
    def description(self) -> str:
        return "List the teammates available in this multi-agent room: id, name and bio (their ability)."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, **kwargs: Any) -> ToolResult:
        agents = [
            {"id": a.id, "name": a.name or a.id, "bio": a.bio, "model_preset": a.preset}
            for a in load_coworker_config().room.agents
        ]
        return self.payload("ok", agents=agents)


@tool_parameters({
    "type": "object",
    "properties": {
        "agent": {"type": "string", "description": 'Target agent id exactly as in agents_list (e.g. "researcher").'},
        "task": {"type": "string", "description": "Concrete, self-contained task: what to produce and any constraints."},
    },
    "required": ["agent", "task"],
})
class RoomDelegateTool(_RoomTool):
    @property
    def name(self) -> str:
        return "room_delegate"

    @property
    def description(self) -> str:
        return (
            "Hand a sub-task to another agent in this room. That agent takes a turn after yours, does the "
            "work with its own tools and reports back. Call once per agent you need, then END your turn; "
            "the room runs them and re-summons the coordinator with their results."
        )

    async def execute(self, agent: str = "", task: str = "", **kwargs: Any) -> ToolResult:
        identity = self._identity()
        if identity is None:
            return self.payload("error", error="room_delegate is only available inside a multi-agent room.")
        session_key, by = identity
        target = agent.strip().lstrip("@").lower()
        if not target or not task.strip():
            return self.payload("error", error="room_delegate requires `agent` and `task`.")
        if load_coworker_config().agent(target) is None:
            return self.payload("error", error=f"unknown agent `{target}` — call agents_list for valid ids.")
        if target == by:
            return self.payload("error", error="you cannot delegate to yourself.")
        request = self.request()
        scheduler.record_delegation(
            session_key, target, task, by=by, runtime=request.runtime if request else None
        )
        return self.payload("ok", delegated=target, note=f"@{target} will take a turn after yours: {task[:120]}")


@tool_parameters({
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["set", "get", "list", "append", "delete"], "description": "What to do."},
        "key": {"type": "string", "description": "Entry key (required for set/get/append/delete)."},
        "value": {"description": "Value to store (required for set). Any JSON shape."},
        "item": {"description": "Item to push (required for append)."},
    },
    "required": ["action"],
})
class RoomStateTool(_RoomTool):
    @property
    def name(self) -> str:
        return "room_state"

    @property
    def description(self) -> str:
        return (
            "Shared key/value scratchpad for the agents in THIS room: post the work-split, save an "
            "intermediate result for another agent, keep a review checklist, list produced artifacts. "
            "Actions: set, get, list, append, delete. Bounds: 50 keys, 32KB per value — store a summary "
            "or a file path, not a whole document. Each write records which agent made it."
        )

    async def execute(
        self,
        action: str = "",
        key: str = "",
        value: Any = None,
        item: Any = None,
        **kwargs: Any,
    ) -> ToolResult:
        identity = self._identity()
        svc = services()
        if identity is None or svc is None:
            return self.payload("error", error="room_state is only available inside a multi-agent room.")
        session_key, by = identity
        store = RoomStateStore(svc.workspace, room_id_for(session_key))
        key = key.strip()
        try:
            if action == "list":
                return self.payload("ok", keys=store.list())
            if not key:
                return self.payload("error", error=f"{action} requires `key`.")
            if action == "get":
                entry = store.get(key)
                if entry is None:
                    return self.payload("not_found", key=key)
                return self.payload("ok", key=key, value=entry.value, by=entry.by)
            if action == "set":
                if value is None:
                    return self.payload("error", error="set requires `value`.")
                store.set(key, value, by)
                return self.payload("ok", key=key, by=by)
            if action == "append":
                if item is None:
                    return self.payload("error", error="append requires `item`.")
                return self.payload("ok", key=key, length=store.append(key, item, by), by=by)
            if action == "delete":
                return self.payload("ok" if store.delete(key) else "not_found", key=key)
        except ValueError as exc:
            return self.payload("error", error=str(exc))
        return self.payload("error", error=f'unknown action "{action}" — use set/get/list/append/delete.')


def room_armed_for(session: Any) -> bool:
    return scheduler.is_armed(session) and bool(load_coworker_config().room.agents)
