"""Tests for Phase 4.5 room queue checkpoint and recovery."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.coworker.commands import cmd_room
from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.room import scheduler
from nanobot.coworker.room.queue_store import RoomQueueStore
from nanobot.coworker.room.scheduler import Delegation, notify_interrupted_rooms
from nanobot.coworker.room.store import room_id_for

KEY = "telegram:checkpoint"
OWNER_RUNTIME: Any = SimpleNamespace(model="owner-model")
CTX = "Sufficient context for test delegations meeting minContextChars requirements."


def _config() -> CoworkerConfig:
    return CoworkerConfig(
        room=RoomConfig(
            agents=[
                RoomAgentConfig(id="agent_a", name="Agent A", bio="alpha"),
                RoomAgentConfig(id="agent_b", name="Agent B", bio="beta"),
            ],
            max_parallel=1,
            max_chained_turns=16,
        )
    )


async def _drain(key: str) -> None:
    room = scheduler._room(key)
    assert room.task is not None
    await room.task


def test_queue_store_round_trip(tmp_path) -> None:
    store = RoomQueueStore(tmp_path, "room_1")
    assert not store.exists()
    assert store.load() is None

    d1 = Delegation(id="1", agent_id="agent_a", task="task 1", by="owner", context=CTX)
    d2 = Delegation(id="2", agent_id="agent_b", task="task 2", by="owner", context=CTX, after=("agent_a",))

    store.save(
        session_key="telegram:123",
        channel="telegram",
        chat_id="123",
        chained=1,
        queued=[d2],
        running=[d1],
        finished={"agent_c"},
    )
    assert store.exists()

    doc = store.load()
    assert doc is not None
    assert doc["version"] == 1
    assert doc["chained"] == 1
    assert doc["finished"] == ["agent_c"]

    unfinished = store.unfinished_delegations()
    assert len(unfinished) == 2
    # running are placed first, then queued
    assert unfinished[0].agent_id == "agent_a"
    assert unfinished[1].agent_id == "agent_b"
    assert unfinished[1].after == ("agent_a",)

    store.clear()
    assert not store.exists()
    assert store.load() is None


@pytest.mark.asyncio
async def test_queue_store_cleared_on_clean_completion(env) -> None:
    env.configure(_config())

    class SimpleSubagents:
        async def run_inline(self, **kwargs: Any) -> str:
            return "done"

    env.subagents = SimpleSubagents()
    env.bind()

    store = RoomQueueStore(env.workspace, room_id_for(KEY))
    scheduler.record_delegation(KEY, "agent_a", "task 1", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="checkpoint")
    await _drain(KEY)

    assert not store.exists()


@pytest.mark.asyncio
async def test_room_resume_runs_unfinished_delegations(env) -> None:
    env.configure(_config())

    calls: list[str] = []

    class RecordSubagents:
        async def run_inline(self, *, label: str, **kwargs: Any) -> str:
            agent = label.removeprefix("room:")
            calls.append(agent)
            return f"Result {agent}"

    env.subagents = RecordSubagents()
    env.bind()

    store = RoomQueueStore(env.workspace, room_id_for(KEY))
    d1 = Delegation(id="d1", agent_id="agent_a", task="resume task A", by="owner", context=CTX)
    d2 = Delegation(id="d2", agent_id="agent_b", task="resume task B", by="owner", context=CTX)
    store.save(
        session_key=KEY,
        channel="telegram",
        chat_id="checkpoint",
        chained=0,
        queued=[d2],
        running=[d1],
        finished=set(),
    )

    ok, msg = scheduler.resume_room(KEY)
    assert ok
    assert "Resuming 2 delegation(s)" in msg

    await _drain(KEY)
    assert calls == ["agent_a", "agent_b"]
    assert not store.exists()


@pytest.mark.asyncio
async def test_cmd_room_resume_and_reset(env) -> None:
    env.configure(_config())

    class RecordSubagents:
        async def run_inline(self, **kwargs: Any) -> str:
            return "ok"

    env.subagents = RecordSubagents()
    env.bind()

    store = RoomQueueStore(env.workspace, room_id_for(KEY))
    d = Delegation(id="d1", agent_id="agent_a", task="resume task", by="owner", context=CTX)
    store.save(
        session_key=KEY,
        channel="telegram",
        chat_id="checkpoint",
        chained=0,
        queued=[d],
        running=[],
        finished=set(),
    )

    ctx = SimpleNamespace(
        key=KEY,
        session=None,
        loop=SimpleNamespace(sessions=env.sessions),
        msg=SimpleNamespace(channel="telegram", chat_id="checkpoint", metadata={}),
        args="resume",
    )
    reply = await cmd_room(ctx)  # type: ignore[arg-type]
    assert "▶️ Resuming 1 delegation(s)" in reply.content
    await _drain(KEY)

    # Test /room reset
    store.save(
        session_key=KEY,
        channel="telegram",
        chat_id="checkpoint",
        chained=0,
        queued=[d],
        running=[],
        finished=set(),
    )
    assert store.exists()
    ctx.args = "reset"
    reply_reset = await cmd_room(ctx)  # type: ignore[arg-type]
    assert "Room: " in reply_reset.content
    assert not store.exists()


@pytest.mark.asyncio
async def test_notify_interrupted_rooms_posts_to_chat(env) -> None:
    env.configure(_config())
    env.bind()

    store = RoomQueueStore(env.workspace, "room_notify")
    d = Delegation(id="d1", agent_id="agent_a", task="unfinished", by="owner", context=CTX)
    store.save(
        session_key="telegram:chat_notify",
        channel="telegram",
        chat_id="chat_notify",
        chained=0,
        queued=[d],
        running=[],
        finished=set(),
    )

    await notify_interrupted_rooms(env.workspace)
    assert len(env.bus.outbound) >= 1
    assert any("Interrupted room detected: 1 unfinished delegation" in m.content for m in env.bus.outbound)
    assert any("/room resume" in m.content for m in env.bus.outbound)
