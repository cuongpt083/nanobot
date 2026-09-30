"""Multi-agent room: shared state bounds, teammate scheduling, chaining, WAIT_FOR, budget."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.room import scheduler
from nanobot.coworker.room.store import MAX_KEYS, RoomStateStore
from nanobot.coworker.room.tools import RoomDelegateTool, RoomStateTool

KEY = "telegram:42"
OWNER_RUNTIME: Any = SimpleNamespace(model="owner-model")


class FakeSubagents:
    """Stands in for SubagentManager.run_inline; replies per agent from a script."""

    def __init__(self, script: dict[str, list[str]], on_run: Any = None) -> None:
        self.script = script
        self.calls: list[tuple[str, str]] = []
        self.on_run = on_run

    async def run_inline(self, *, task: str, label: str, **kwargs: Any) -> str:
        agent = label.removeprefix("room:")
        actor = scheduler.current_room_actor.get()
        assert actor is not None and actor.agent_id == agent
        self.calls.append((agent, task))
        if self.on_run is not None:
            await self.on_run(agent)
        return self.script[agent].pop(0)


def _config(max_chained: int = 16) -> CoworkerConfig:
    return CoworkerConfig(room=RoomConfig(
        agents=[
            RoomAgentConfig(id="researcher", name="Researcher", emoji="🔎", bio="finds facts"),
            RoomAgentConfig(id="writer", name="Writer", bio="writes copy"),
        ],
        max_chained_turns=max_chained,
    ))


async def _drain(key: str) -> None:
    room = scheduler._room(key)
    assert room.task is not None
    await room.task


def test_room_state_store_bounds(tmp_path) -> None:
    store = RoomStateStore(tmp_path, "r")
    store.set("plan", {"a": 1}, "owner")
    assert store.append("findings", "x", "researcher") == 1
    assert store.get("plan").value == {"a": 1}
    with pytest.raises(ValueError):
        store.append("plan", "y", "owner")
    with pytest.raises(ValueError):
        store.set("big", "x" * 40_000, "owner")
    for i in range(MAX_KEYS - 2):
        store.set(f"k{i}", i, "owner")
    with pytest.raises(ValueError):
        store.set("overflow", 1, "owner")


@pytest.mark.asyncio
async def test_delegations_run_teammates_then_summon_the_coordinator(env) -> None:
    env.configure(_config())
    env.subagents = FakeSubagents({"researcher": ["Facts: A, B"], "writer": ["Draft copy"]})
    env.bind()
    with request_context(RequestContext(channel="telegram", chat_id="42", session_key=KEY, runtime=OWNER_RUNTIME)):
        tool = RoomDelegateTool()
        ok = json.loads(await tool.execute(agent="@Researcher", task="find facts"))
        assert ok["status"] == "ok"
        await tool.execute(agent="writer", task="write copy")
        bad = json.loads(await tool.execute(agent="ghost", task="x"))
        assert bad["status"] == "error"

    assert scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)

    assert [agent for agent, _ in env.subagents.calls] == ["researcher", "writer"]
    assert "## Your assignment (from owner)\nfind facts" in env.subagents.calls[0][1]
    # The writer sees the researcher's result in the room projection.
    assert "@researcher: Facts: A, B" in env.subagents.calls[1][1]
    posted = [m.content for m in env.bus.outbound]
    assert any(p.startswith("🔎 Researcher:\nFacts: A, B") for p in posted)
    review = env.bus.inbound[-1]
    assert review.content.startswith("[auto-room]") and review.session_key_override == KEY
    assert review.chat_id == "telegram:42" and review.metadata["coworker_kind"] == "room_review"


@pytest.mark.asyncio
async def test_teammate_can_delegate_onward_and_wait_for_dependencies(env) -> None:
    env.configure(_config())

    async def on_run(agent: str) -> None:
        if agent == "writer" and len(env.subagents.calls) == 1:
            # Writer hands research to the researcher through its own tool call.
            await RoomDelegateTool().execute(agent="researcher", task="get numbers")

    env.subagents = FakeSubagents(
        {"writer": ["WAIT_FOR @researcher\nneed numbers", "Final copy with numbers"], "researcher": ["42%"]},
        on_run=on_run,
    )
    env.bind()
    scheduler.record_delegation(KEY, "writer", "write copy", by="owner", runtime=OWNER_RUNTIME)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)
    assert [a for a, _ in env.subagents.calls] == ["writer", "researcher", "writer"]
    assert any("waits for @researcher" in m.content for m in env.bus.outbound)
    assert "Final copy with numbers" in env.bus.inbound[-1].content


@pytest.mark.asyncio
async def test_chained_turn_budget_pauses_the_room(env) -> None:
    env.configure(_config(max_chained=1))
    env.subagents = FakeSubagents({"researcher": ["done"], "writer": ["done"]})
    env.bind()
    scheduler.record_delegation(KEY, "researcher", "a", by="owner", runtime=OWNER_RUNTIME)
    scheduler.record_delegation(KEY, "writer", "b", by="owner", runtime=OWNER_RUNTIME)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)
    assert len(env.subagents.calls) == 1
    assert any(m.content.startswith("⏸️ Room paused") for m in env.bus.outbound)


@pytest.mark.asyncio
async def test_room_state_tool_records_the_acting_agent(env) -> None:
    env.configure(_config())
    tool = RoomStateTool()
    with request_context(RequestContext(channel="telegram", chat_id="42", session_key=KEY, runtime=OWNER_RUNTIME)):
        await tool.execute(action="set", key="plan", value=["research", "write"])
        token = scheduler.current_room_actor.set(scheduler.RoomActor("x", KEY, "researcher"))
        try:
            await tool.execute(action="append", key="findings", item="fact 1")
        finally:
            scheduler.current_room_actor.reset(token)
        listing = json.loads(await tool.execute(action="list"))
    assert {k["key"]: k["by"] for k in listing["keys"]} == {"findings": "researcher", "plan": "owner"}
