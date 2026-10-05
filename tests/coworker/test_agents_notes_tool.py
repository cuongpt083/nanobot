from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.coworker.agents.home import scaffold_agent_home
from nanobot.coworker.agents.notes_tool import MAX_NOTE_CHARS, AgentNotesTool
from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, set_coworker_config_override
from nanobot.coworker.room.scheduler import RoomActor, current_room_actor
from nanobot.coworker.runtime import CoworkerServices, set_services


def _payload(result: object) -> dict[str, object]:
    return json.loads(str(result))


@pytest.mark.asyncio
async def test_notes_tool_disabled_outside_room_or_without_thread_notes(tmp_path: Path) -> None:
    tool = AgentNotesTool()
    res = _payload(await tool.execute(action="list"))
    assert res["status"] == "error"
    assert "only available during an active room turn" in str(res["error"])

    cfg = CoworkerConfig()
    cfg.room.agents = [
        RoomAgentConfig(id="agent1", memory="thread", home="agents/agent1"),
        RoomAgentConfig(id="agent2", memory="thread+notes", home="agents/agent2"),
    ]
    set_coworker_config_override(cfg)
    set_services(
        CoworkerServices(
            workspace=tmp_path,
            bus=None,  # type: ignore[arg-type]
            sessions=None,  # type: ignore[arg-type]
            subagents=None,
            provider_snapshot_loader=None,
        )
    )
    tok = current_room_actor.set(RoomActor(room_id="r1", session_key="s1", agent_id="agent1"))
    try:
        res1 = _payload(await tool.execute(action="list"))
        assert res1["status"] == "error"
        assert "does not have memory='thread+notes'" in str(res1["error"])
    finally:
        current_room_actor.reset(tok)
        set_coworker_config_override(None)
        set_services(None)


@pytest.mark.asyncio
async def test_notes_tool_append_and_list_and_limits(tmp_path: Path) -> None:
    cfg = CoworkerConfig()
    agent2 = RoomAgentConfig(id="agent2", memory="thread+notes", home="agents/agent2")
    cfg.room.agents = [agent2]
    set_coworker_config_override(cfg)
    scaffold_agent_home(tmp_path, agent2)
    set_services(
        CoworkerServices(
            workspace=tmp_path,
            bus=None,  # type: ignore[arg-type]
            sessions=None,  # type: ignore[arg-type]
            subagents=None,
            provider_snapshot_loader=None,
        )
    )

    tool = AgentNotesTool()
    tok = current_room_actor.set(RoomActor(room_id="r1", session_key="s1", agent_id="agent2"))
    try:
        listed = _payload(await tool.execute(action="list"))
        assert listed["status"] == "ok"
        assert "Always use strict typing." not in str(listed.get("notes"))

        appended = _payload(await tool.execute(action="append", note="Always use strict typing."))
        assert appended["status"] == "ok"
        assert appended.get("recorded") == "Always use strict typing."

        listed2 = _payload(await tool.execute(action="list"))
        assert "Always use strict typing." in str(listed2.get("notes"))

        too_long = _payload(await tool.execute(action="append", note="a" * (MAX_NOTE_CHARS + 1)))
        assert too_long["status"] == "error"
        assert "exceeds maximum length" in str(too_long["error"])
    finally:
        current_room_actor.reset(tok)
        set_coworker_config_override(None)
        set_services(None)
