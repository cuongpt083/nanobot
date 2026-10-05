"""room_delegate v2: required context, after validation, structured assignment."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.coworker.agents.runtime import GuestResult
from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.room import scheduler
from nanobot.coworker.room.store import RoomStateStore, room_id_for
from nanobot.coworker.room.tools import RoomDelegateTool

KEY = "telegram:42"
OWNER_RUNTIME: Any = SimpleNamespace(model="owner-model")
CTX = (
    "User already decided: no medical diagnosis, low budget, deliver via Zalo "
    "each morning, keep the tone practical and short for office workers."
)


def _config() -> CoworkerConfig:
    return CoworkerConfig(room=RoomConfig(
        agents=[
            RoomAgentConfig(id="researcher", name="Researcher", emoji="🔎", bio="finds facts"),
            RoomAgentConfig(id="writer", name="Writer", bio="writes copy"),
        ],
    ))


@pytest.mark.asyncio
async def test_missing_context_is_rejected(env) -> None:
    env.configure(_config())
    env.bind()
    with request_context(RequestContext(channel="telegram", chat_id="42", session_key=KEY, runtime=OWNER_RUNTIME)):
        tool = RoomDelegateTool()
        missing = json.loads(await tool.execute(agent="researcher", task="find facts"))
        assert missing["status"] == "error"
        assert "context" in missing["error"]
        short = json.loads(await tool.execute(agent="researcher", task="find facts", context="too short"))
        assert short["status"] == "error"
        assert "80" in short["error"]
    assert scheduler.pending_delegations(KEY) == []


@pytest.mark.asyncio
async def test_after_unknown_id_is_rejected(env) -> None:
    env.configure(_config())
    env.bind()
    with request_context(RequestContext(channel="telegram", chat_id="42", session_key=KEY, runtime=OWNER_RUNTIME)):
        tool = RoomDelegateTool()
        bad = json.loads(await tool.execute(
            agent="writer", task="write copy", context=CTX, after=["researcher"],
        ))
        assert bad["status"] == "error"
        assert "after" in bad["error"]
        ok = json.loads(await tool.execute(agent="researcher", task="find facts", context=CTX))
        assert ok["status"] == "ok"
        chained = json.loads(await tool.execute(
            agent="writer", task="write copy", context=CTX, after=["researcher"], deliverable="one page",
        ))
        assert chained["status"] == "ok"
    pending = scheduler.pending_delegations(KEY)
    assert [d.agent_id for d in pending] == ["researcher", "writer"]
    assert pending[1].after == ("researcher",)
    assert pending[1].deliverable == "one page"


@pytest.mark.asyncio
async def test_task_message_includes_context_state_and_upstream(env) -> None:
    env.configure(_config())
    env.bind()
    session = env.sessions.get_or_create(KEY)
    session.messages.append({"role": "user", "content": "Please plan an 8-week office habit program."})
    env.sessions.save(session)
    store = RoomStateStore(env.workspace, room_id_for(KEY))
    store.set("brief", {"budget": "low"}, "owner")
    room = scheduler._room(KEY)
    room.last_guest["researcher"] = GuestResult(
        text="ignored",
        contract={"summary": "desk stretches work", "confidence": "high", "artifacts": ["notes.md"]},
    )
    delegation = scheduler.Delegation(
        agent_id="writer",
        task="write the plan",
        by="owner",
        context=CTX,
        context_keys=("brief",),
        after=("researcher",),
        deliverable="8-week markdown table",
    )
    text = scheduler._task_message(room, session, delegation)
    assert "## Assignment" in text and "write the plan" in text
    assert "8-week markdown table" in text
    assert "## Context from coordinator" in text and "Zalo" in text
    assert "## Shared state" in text and "brief" in text
    assert "## Upstream results" in text and "desk stretches work" in text
    assert "notes.md" in text
    assert "## Recent user turns" in text and "8-week office habit" in text
    assert "artifacts" in text


@pytest.mark.asyncio
async def test_after_runs_dependent_after_upstream(env) -> None:
    from tests.coworker.test_room import FakeSubagents, _drain

    env.configure(_config())
    env.subagents = FakeSubagents({"researcher": ["Facts: A"], "writer": ["Draft"]})
    env.bind()
    scheduler.record_delegation(
        KEY, "writer", "write copy", by="owner", runtime=OWNER_RUNTIME, context=CTX, after=["researcher"],
    )
    scheduler.record_delegation(
        KEY, "researcher", "find facts", by="owner", runtime=OWNER_RUNTIME, context=CTX,
    )
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)
    assert [agent for agent, _ in env.subagents.calls] == ["researcher", "writer"]
    assert "Facts: A" in env.subagents.calls[1][1]


@pytest.mark.asyncio
async def test_coordinator_review_ranks_low_confidence_first(env) -> None:
    env.configure(_config())
    env.bind()
    room = scheduler._room(KEY)
    room.channel, room.chat_id = "telegram", "42"
    room.last_guest["researcher"] = GuestResult(
        text="facts",
        contract={"summary": "solid research", "confidence": "high"},
    )
    room.last_guest["writer"] = GuestResult(
        text="copy",
        contract={"summary": "needs sources", "confidence": "low", "open_questions": ["cite?"]},
    )
    from nanobot.coworker.config import load_coworker_config

    cfg = load_coworker_config()
    researcher = cfg.agent("researcher")
    writer = cfg.agent("writer")
    assert researcher is not None and writer is not None
    await scheduler._summon_coordinator(
        room,
        [(researcher, "facts"), (writer, "copy")],
        last_guest=dict(room.last_guest),
    )
    review = env.bus.inbound[-1].content
    assert review.index("`writer`") < review.index("`researcher`")
    assert "confidence: low" in review
    assert "needs sources" in review
