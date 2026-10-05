from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.router import CommandContext
from nanobot.coworker.agents.thread import (
    AgentThreadStore,
    clear_room_threads,
)
from nanobot.coworker.commands import cmd_room
from nanobot.coworker.config import (
    CoworkerConfig,
    RoomAgentConfig,
    RoomConfig,
    set_coworker_config_override,
)
from nanobot.coworker.room.store import room_id_for
from nanobot.coworker.runtime import CoworkerServices, set_services


def test_thread_store_append_and_recent(tmp_path: Path):
    store = AgentThreadStore(tmp_path, "coder", "room1")
    assert store.recent(5) == []

    store.append_turn(task="fix the bug", reply="fixed the bug")
    store.append_turn(task="add unit test", reply="added unit test")

    recent = store.recent(1)
    assert len(recent) == 2
    assert recent[0] == {"role": "user", "content": "add unit test"}
    assert recent[1] == {"role": "assistant", "content": "added unit test"}

    recent_all = store.recent(5)
    assert len(recent_all) == 4
    assert recent_all[0]["content"] == "fix the bug"
    assert recent_all[2]["content"] == "add unit test"


def test_thread_store_truncation(tmp_path: Path):
    store = AgentThreadStore(tmp_path, "coder", "room1")
    huge_task = "x" * 6000
    huge_reply = "y" * 6000
    store.append_turn(task=huge_task, reply=huge_reply)

    recent = store.recent(1)
    assert len(recent[0]["content"]) == 4000
    assert len(recent[1]["content"]) == 4000


def test_thread_store_clear_and_clear_room(tmp_path: Path):
    store1 = AgentThreadStore(tmp_path, "coder", "room1")
    store2 = AgentThreadStore(tmp_path, "reviewer", "room1")
    store3 = AgentThreadStore(tmp_path, "coder", "room2")

    store1.append_turn(task="t1", reply="r1")
    store2.append_turn(task="t2", reply="r2")
    store3.append_turn(task="t3", reply="r3")

    assert len(store1.recent(1)) == 2
    assert len(store2.recent(1)) == 2
    assert len(store3.recent(1)) == 2

    # Clear room1 threads across all agents
    clear_room_threads(tmp_path, "room1")

    assert store1.recent(1) == []
    assert store2.recent(1) == []
    assert len(store3.recent(1)) == 2

    store3.clear()
    assert store3.recent(1) == []


def test_thread_store_invalid_names(tmp_path: Path):
    with pytest.raises(ValueError):
        AgentThreadStore(tmp_path, "../bad", "room1")
    with pytest.raises(ValueError):
        AgentThreadStore(tmp_path, "coder", "../bad")


@pytest.mark.asyncio
async def test_room_reset_clears_agent_threads(tmp_path: Path) -> None:
    key = "telegram:42"
    store = AgentThreadStore(tmp_path, "coder", room_id_for(key))
    store.append_turn(task="t1", reply="r1")
    assert store.recent(1)

    set_coworker_config_override(CoworkerConfig(room=RoomConfig(agents=[RoomAgentConfig(id="coder")])))
    set_services(
        CoworkerServices(
            workspace=tmp_path,
            bus=None,  # type: ignore[arg-type]
            sessions=None,  # type: ignore[arg-type]
            subagents=None,
            provider_snapshot_loader=None,
        )
    )
    try:
        msg = InboundMessage(channel="telegram", sender_id="1", chat_id="42", content="/room reset")
        ctx = CommandContext(
            msg=msg,
            session=MagicMock(),
            key=key,
            raw="/room reset",
            args="reset",
            loop=MagicMock(),
        )
        await cmd_room(ctx)
        assert store.recent(1) == []
    finally:
        set_coworker_config_override(None)
        set_services(None)
