"""Tests for coworker session status projection."""

from nanobot.coworker.status import coworker_session_status
from nanobot.session.manager import Session


def test_coworker_session_status_default() -> None:
    session = Session(key="websocket:test-coworker-123", messages=[])
    status = coworker_session_status(session)

    assert "caching" in status
    assert "advisor" in status
    assert "room" in status
    assert "coding" in status

    assert isinstance(status["caching"]["is_warm"], bool)
    assert isinstance(status["caching"]["ttl_seconds"], float)
    assert isinstance(status["advisor"]["enabled"], bool)
    assert isinstance(status["room"]["armed"], bool)
    assert isinstance(status["coding"]["tasks"], list)


def _by_id(status: dict, pid: str) -> dict:
    return next(p for p in status["participants"] if p["id"] == pid)


def test_participants_default_to_the_idle_coordinator_only(env) -> None:
    status = coworker_session_status(env.sessions.get_or_create("cli:direct"))
    assert [(p["id"], p["kind"], p["state"]) for p in status["participants"]] == [
        ("coordinator", "coordinator", "idle")
    ]
    assert status["advisor"]["last_consult"] is None


def test_participants_reflect_coordinator_advisor_room_and_coding(env) -> None:
    import time as _time

    from nanobot.coworker.advisor import consult as advisor_consult
    from nanobot.coworker.coding.tasks import CodingTask, shared_registry
    from nanobot.coworker.config import (
        AdvisorConfig,
        CodingAgentConfig,
        CoworkerConfig,
        RoomAgentConfig,
        RoomConfig,
    )
    from nanobot.coworker.room import scheduler
    from nanobot.coworker.runtime import mark_turn_running

    key = "cli:direct"
    env.configure(CoworkerConfig(
        advisor=AdvisorConfig(preset="strong"),
        room=RoomConfig(agents=[
            RoomAgentConfig(id="researcher", name="Researcher", emoji="🔎"),
            RoomAgentConfig(id="writer", name="Writer"),
            RoomAgentConfig(id="coder", backend="pi"),
        ]),
        coding=CodingAgentConfig(enabled=True),
    ))
    session = env.sessions.get_or_create(key)
    scheduler.set_armed(session, True)
    mark_turn_running(key)
    advisor_consult._active[key] = advisor_consult.ActiveConsult(_time.time(), "strong-model", "review diff")

    room = scheduler._room(key)
    room.active["researcher"] = scheduler.ActiveGuest("researcher", "find facts", _time.time())
    room.queued = [scheduler.Delegation("writer", "write copy", "owner")]
    room.outcome("coder", "timeout")

    registry = shared_registry(env.workspace)
    running = CodingTask(id="ct-1", backend="pi", session_key=key, channel="cli", chat_id="u", repo="/r",
                         base="main", branch="b", worktree="/w", brief="add flag", status="running")
    running.live = {"tool_count": 7, "last_tool": "run_command", "rounds": 2, "last_event_at": _time.time()}
    other = CodingTask(id="ct-2", backend="agy", session_key="cli:someone-else", channel="cli", chat_id="u",
                       repo="/r", base="main", branch="b", worktree="/w", brief="not mine", status="running")
    registry.save(running)
    registry.save(other)

    status = coworker_session_status(session)
    assert _by_id(status, "coordinator")["state"] == "working"
    advisor = _by_id(status, "advisor")
    assert advisor["state"] == "working" and advisor["task"] == "review diff"
    assert advisor["engine"] == "preset:strong"
    researcher = _by_id(status, "researcher")
    assert researcher["state"] == "working" and researcher["task"] == "find facts"
    assert researcher["label"] == "🔎 Researcher" and researcher["engine"] == "preset:default"
    assert _by_id(status, "writer")["state"] == "queued"
    coder = _by_id(status, "coder")
    assert coder["state"] == "error" and coder["engine"] == "backend:pi"
    task = _by_id(status, "ct-1")
    assert task["kind"] == "coding" and task["state"] == "working"
    assert task["detail"]["tools"] == 7 and task["detail"]["last_tool"] == "run_command"
    assert task["detail"]["rounds"] == 2
    # Tasks of other sessions are never listed.
    assert [t["id"] for t in status["coding"]["tasks"]] == ["ct-1"]
    assert not any(p["id"] == "ct-2" for p in status["participants"])


def test_unarmed_room_only_lists_teammates_that_are_doing_something(env) -> None:
    from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig

    env.configure(CoworkerConfig(room=RoomConfig(agents=[RoomAgentConfig(id="researcher")])))
    status = coworker_session_status(env.sessions.get_or_create("cli:direct"))
    assert all(p["kind"] != "teammate" for p in status["participants"])
