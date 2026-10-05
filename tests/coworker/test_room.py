"""Multi-agent room: shared state bounds, teammate scheduling, chaining, WAIT_FOR, budget."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.coworker.agents.home import scaffold_agent_home
from nanobot.coworker.agents.runtime import GuestResult
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
    first_task = env.subagents.calls[0][1]
    assert first_task.startswith('You are agent "Researcher" (id `researcher`)')
    assert "## Your assignment (from owner)\nfind facts" in first_task
    assert "\n\n---\n\n" in first_task
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


@pytest.mark.asyncio
async def test_room_snapshot_tracks_active_queued_and_recent(env) -> None:
    env.configure(_config())
    seen: dict[str, Any] = {}

    async def on_run(agent: str) -> None:
        if agent == "researcher":
            seen["mid"] = scheduler.room_snapshot(KEY)

    env.subagents = FakeSubagents({"researcher": ["Facts"], "writer": ["Copy"]}, on_run=on_run)
    env.bind()
    scheduler.record_delegation(KEY, "researcher", "find facts", by="owner", runtime=OWNER_RUNTIME)
    scheduler.record_delegation(KEY, "writer", "write copy", by="owner", runtime=OWNER_RUNTIME)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)

    mid = seen["mid"]
    assert [g.agent_id for g in mid.active] == ["researcher"] and mid.active[0].task == "find facts"
    assert [d.agent_id for d in mid.queued] == ["writer"]

    after = scheduler.room_snapshot(KEY)
    assert after.active == [] and after.queued == [] and after.waiting == {}
    assert [(o.agent_id, o.state) for o in after.recent] == [("researcher", "done"), ("writer", "done")]


@pytest.mark.asyncio
async def test_room_snapshot_marks_waiting_and_failed_agents(env) -> None:
    env.configure(_config())
    seen: dict[str, Any] = {}

    async def on_run(agent: str) -> None:
        if agent == "writer" and len(env.subagents.calls) == 1:
            await RoomDelegateTool().execute(agent="researcher", task="get numbers")
        if agent == "researcher":
            seen["snap"] = scheduler.room_snapshot(KEY)

    env.subagents = FakeSubagents(
        {"writer": ["WAIT_FOR @researcher\nneed numbers", "Final"], "researcher": ["42%"]}, on_run=on_run,
    )
    env.bind()
    scheduler.record_delegation(KEY, "writer", "write copy", by="owner", runtime=OWNER_RUNTIME)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)
    assert seen["snap"].waiting == {"writer": "researcher"}
    assert scheduler.room_snapshot(KEY).waiting == {}

    class Boom(FakeSubagents):
        async def run_inline(self, **kwargs: Any) -> str:
            raise RuntimeError("model down")

    env.subagents = Boom({})
    env.bind()
    scheduler.record_delegation(KEY, "researcher", "again", by="owner", runtime=OWNER_RUNTIME)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)
    last_outcome = scheduler.room_snapshot(KEY).recent[-1]
    assert last_outcome.state == "error"
    assert last_outcome.duration_s >= 0.0


@pytest.mark.asyncio
async def test_guest_outcome_records_duration(env) -> None:
    import asyncio

    env.configure(_config())

    class SleepySubagents(FakeSubagents):
        async def run_inline(self, **kwargs: Any) -> str:
            await asyncio.sleep(0.05)
            return "done sleeping"

    env.subagents = SleepySubagents({"researcher": ["done"]})
    env.bind()
    scheduler.record_delegation(KEY, "researcher", "work", by="owner", runtime=OWNER_RUNTIME)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)

    snap = scheduler.room_snapshot(KEY)
    assert len(snap.recent) == 1
    outcome = snap.recent[0]
    assert outcome.agent_id == "researcher"
    assert outcome.state == "done"
    assert outcome.duration_s >= 0.04
    assert outcome.tokens_in is None
    assert outcome.tokens_out is None


@pytest.mark.asyncio
async def test_home_guest_uses_agent_runtime_and_records_tokens(env, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = RoomAgentConfig(id="researcher", name="Researcher", emoji="🔎", home="agents/researcher")
    scaffold_agent_home(env.workspace, agent)
    env.configure(CoworkerConfig(room=RoomConfig(agents=[agent])))
    env.bind()

    seen: dict[str, Any] = {}

    async def fake_run(self, guest_agent, task_msg, **kwargs: Any) -> GuestResult:
        seen["task"] = task_msg
        seen["agent"] = guest_agent.id
        seen["progress"] = kwargs.get("progress")
        return GuestResult(
            text="home reply",
            usage={"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        )

    monkeypatch.setattr("nanobot.coworker.agents.runtime.AgentRuntime.run", fake_run)
    scheduler.record_delegation(KEY, "researcher", "find facts", by="owner", runtime=OWNER_RUNTIME)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)

    assert seen["agent"] == "researcher"
    assert "## Your assignment (from owner)\nfind facts" in seen["task"]
    assert seen["progress"] is None or seen["progress"].agent_id == "researcher"
    outcome = scheduler.room_snapshot(KEY).recent[-1]
    assert outcome.state == "done"
    assert outcome.tokens_in == 12
    assert outcome.tokens_out == 4
    posted = [m.content for m in env.bus.outbound]
    assert any("home reply" in p for p in posted)


@pytest.mark.asyncio
async def test_home_agent_two_turn_thread_binds_session_workspace(env) -> None:
    from agent.conftest import make_provider

    from nanobot.coworker.runtime import services
    from nanobot.providers.base import LLMResponse, LLMUsage
    from nanobot.security.workspace_access import current_workspace_scope
    from nanobot.utils.llm_runtime import LLMRuntime

    agent = RoomAgentConfig(id="researcher", name="Researcher", emoji="🔎", home="agents/researcher")
    scaffold_agent_home(env.workspace, agent)
    (env.workspace / "agents" / "researcher" / "SOUL.md").write_text(
        "# Unique Soul Marker\nI am the specialist.",
        encoding="utf-8",
    )
    proj = env.workspace / "proj"
    proj.mkdir()
    env.configure(CoworkerConfig(room=RoomConfig(agents=[agent])))
    env.bind()
    session = env.sessions.get_or_create(KEY)
    session.metadata["workspace_scope"] = {
        "project_path": str(proj.resolve()),
        "access_mode": "restricted",
    }
    env.sessions.save(session)

    captured: list[dict[str, Any]] = []
    replies = ["r1", "r2"]

    async def _record(*_args: Any, **kwargs: Any) -> LLMResponse:
        scope = current_workspace_scope()
        captured.append({
            "messages": kwargs["messages"],
            "scope_path": scope.project_path if scope is not None else None,
            "restrict": scope.restrict_to_workspace if scope is not None else None,
        })
        return LLMResponse(
            content=replies[len(captured) - 1],
            usage=LLMUsage.estimated(input_tokens=5, output_tokens=3),
        )

    provider = make_provider()
    provider.chat_stream_with_retry = _record
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128_000)
    before = id(services())

    scheduler.record_delegation(KEY, "researcher", "first task", by="owner", runtime=runtime)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)
    scheduler.record_delegation(KEY, "researcher", "second task", by="owner", runtime=runtime)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)

    assert len(captured) == 2
    assert any("Unique Soul Marker" in str(m.get("content")) for m in captured[0]["messages"])
    second_contents = [str(m.get("content")) for m in captured[1]["messages"]]
    assert any("first task" in content for content in second_contents)
    assert any("r1" in content for content in second_contents)
    assert captured[0]["scope_path"] == proj.resolve()
    assert captured[1]["scope_path"] == proj.resolve()
    assert captured[0]["restrict"] is True
    outcome = scheduler.room_snapshot(KEY).recent[-1]
    assert outcome.state == "done"
    assert outcome.tokens_in == 5
    assert outcome.tokens_out == 3
    assert id(services()) == before


@pytest.mark.asyncio
async def test_stale_workspace_scope_falls_back_to_workspace(env) -> None:
    from agent.conftest import make_provider

    from nanobot.providers.base import LLMResponse, LLMUsage
    from nanobot.security.workspace_access import current_workspace_scope
    from nanobot.utils.llm_runtime import LLMRuntime

    agent = RoomAgentConfig(id="researcher", name="Researcher", home="agents/researcher")
    scaffold_agent_home(env.workspace, agent)
    env.configure(CoworkerConfig(room=RoomConfig(agents=[agent])))
    env.bind()
    session = env.sessions.get_or_create(KEY)
    session.metadata["workspace_scope"] = {
        "project_path": str(env.workspace / "missing-dir"),
        "access_mode": "restricted",
    }
    env.sessions.save(session)

    seen: dict[str, Any] = {}

    async def _record(*_args: Any, **kwargs: Any) -> LLMResponse:
        scope = current_workspace_scope()
        seen["scope_path"] = scope.project_path if scope is not None else None
        return LLMResponse(
            content="ok",
            usage=LLMUsage.estimated(input_tokens=1, output_tokens=1),
        )

    provider = make_provider()
    provider.chat_stream_with_retry = _record
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128_000)
    scheduler.record_delegation(KEY, "researcher", "work", by="owner", runtime=runtime)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="42")
    await _drain(KEY)

    assert seen["scope_path"] == env.workspace.resolve()
    assert scheduler.room_snapshot(KEY).recent[-1].state == "done"


@pytest.mark.asyncio
async def test_self_delegate_forbidden_when_wearing_persona(env) -> None:
    from nanobot.coworker.persona import set_persona_id

    cfg = _config()
    env.configure(cfg)
    session = env.sessions.get_or_create(KEY)
    set_persona_id(session, "researcher", cfg)

    with request_context(RequestContext(channel="telegram", chat_id="42", session_key=KEY, runtime=OWNER_RUNTIME)):
        tool = RoomDelegateTool()
        # Delegating to researcher while wearing researcher persona is rejected
        res = json.loads(await tool.execute(agent="researcher", task="find facts"))
        assert res["status"] == "error"
        assert "you are currently @researcher" in res["error"]

        # Delegating to writer works
        ok = json.loads(await tool.execute(agent="writer", task="write copy"))
        assert ok["status"] == "ok"


def test_persona_excluded_from_room_owner_roster(env) -> None:
    from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
    from nanobot.coworker.hook import CoworkerHook
    from nanobot.coworker.persona import set_persona_id

    cfg = _config()
    env.configure(cfg)
    session = env.sessions.get_or_create(KEY)
    set_persona_id(session, "researcher", cfg)
    scheduler.set_armed(session, True)

    hook = CoworkerHook(
        AgentTurnHookContext(channel="telegram", chat_id="42", session_key=KEY)
    )
    agent_ctx = AgentHookContext(iteration=0, messages=[])
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "BASE_PROMPT"},
        {"role": "user", "content": "Hello"},
    ]

    out_msgs, _ = hook.transform_request(agent_ctx, messages, None, stateful=False)
    sys_content = out_msgs[0]["content"]

    # Roster has writer, but researcher is excluded from the Multi-agent room section
    assert "## Multi-agent room" in sys_content
    room_section = sys_content.split("## Multi-agent room", 1)[1]
    assert "- `writer` — Writer" in room_section
    assert "- `researcher`" not in room_section

    # If all agents are excluded, roster shows fallback note
    single_agent_cfg = CoworkerConfig(
        room=RoomConfig(
            agents=[RoomAgentConfig(id="researcher", name="Researcher", bio="finds facts")]
        )
    )
    env.configure(single_agent_cfg)
    set_persona_id(session, "researcher", single_agent_cfg)
    out_msgs2, _ = hook.transform_request(agent_ctx, messages, None, stateful=False)
    sys_content2 = out_msgs2[0]["content"]
    assert "- _(no other teammates available)_" in sys_content2


@pytest.mark.asyncio
async def test_mentioning_own_persona_does_not_arm_room(env) -> None:
    from nanobot.agent.hook import AgentRunHookContext, AgentTurnHookContext
    from nanobot.coworker.hook import CoworkerHook
    from nanobot.coworker.persona import set_persona_id

    cfg = _config()
    env.configure(cfg)
    session = env.sessions.get_or_create(KEY)
    set_persona_id(session, "researcher", cfg)
    assert not scheduler.is_armed(session)

    hook = CoworkerHook(
        AgentTurnHookContext(channel="telegram", chat_id="42", session_key=KEY)
    )
    # Mentioning @researcher when wearing researcher persona does not arm the room
    run_ctx1 = AgentRunHookContext(messages=[{"role": "user", "content": "Please check this @researcher"}])
    await hook.before_run(run_ctx1)
    assert not scheduler.is_armed(session)

    # Mentioning @writer arms the room
    run_ctx2 = AgentRunHookContext(messages=[{"role": "user", "content": "Please check this @writer"}])
    await hook.before_run(run_ctx2)
    assert scheduler.is_armed(session)


