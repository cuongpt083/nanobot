"""CoworkerHook: per-session tool visibility, directives, and after-run orchestration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.agent.hook import AgentHookContext, AgentRunHookContext, AgentTurnHookContext
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.config import AdvisorConfig, CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.hook import ADVISOR_REVIEW_MARKER, CoworkerHook
from nanobot.coworker.room import scheduler
from nanobot.coworker.workflows import drive

KEY = "cli:direct"
ALL_TOOLS = [
    {"type": "function", "function": {"name": n}}
    for n in ("read_file", "advisor", "room_delegate", "room_state", "agents_list",
              "mark_context_wasted", "workflow_run", "workflow_distill")
]


def _hook(metadata: dict | None = None) -> CoworkerHook:
    return CoworkerHook(AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY,
                                             metadata=metadata or {}))


def _names(tools) -> set[str]:
    return {t["function"]["name"] for t in tools}


def _transform(hook: CoworkerHook):
    return hook.transform_request(
        AgentHookContext(iteration=0, messages=[]),
        [{"role": "system", "content": "BASE"}, {"role": "user", "content": "hi"}],
        list(ALL_TOOLS),
        stateful=False,
    )


def test_plain_session_hides_feature_tools(env) -> None:
    env.sessions.get_or_create(KEY)
    messages, tools = _transform(_hook())
    assert _names(tools) == {"read_file", "workflow_run", "workflow_distill"}
    assert messages[0]["content"] == "BASE"


def test_enabled_features_expose_tools_and_directives(env) -> None:
    env.configure(CoworkerConfig(
        advisor=AdvisorConfig(preset="strong"),
        room=RoomConfig(agents=[RoomAgentConfig(id="researcher", bio="finds facts")]),
    ))
    session = env.sessions.get_or_create(KEY)
    scheduler.set_armed(session, True)
    messages, tools = _transform(_hook())
    assert {"advisor", "room_delegate", "room_state", "agents_list"} <= _names(tools)
    system = messages[0]["content"]
    assert system.startswith("BASE\n\n## Advisor") and "## Multi-agent room" in system
    assert "`researcher`" in system


@pytest.mark.asyncio
async def test_user_mention_arms_the_room(env) -> None:
    env.configure(CoworkerConfig(room=RoomConfig(agents=[RoomAgentConfig(id="researcher")])))
    session = env.sessions.get_or_create(KEY)
    await _hook().before_run(AgentRunHookContext(messages=[{"role": "user", "content": "ask @researcher"}]))
    assert scheduler.is_armed(session)


def _run(tools_used: list[str], messages=None) -> AgentRunHookContext:
    return AgentRunHookContext(messages=messages or [{"role": "user", "content": "build it"}],
                               final_content="done", tools_used=tools_used, stop_reason="completed")


@pytest.mark.asyncio
async def test_advisor_review_nudge_after_unreviewed_work(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    monkeypatch.setattr("nanobot.coworker.runtime.runtime_for_preset",
                        lambda preset: SimpleNamespace(model="strong-model"))
    env.sessions.get_or_create(KEY)
    hook = _hook()
    ctx = _run(["write_file", "exec"])
    await hook.before_run(ctx)
    await hook.after_run(ctx)
    assert len(env.bus.inbound) == 1
    nudge = env.bus.inbound[0]
    assert nudge.content.startswith(ADVISOR_REVIEW_MARKER)
    assert nudge.metadata["coworker_kind"] == "advisor_review"


@pytest.mark.asyncio
async def test_no_nudge_when_consulted_or_injected(env) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    env.sessions.get_or_create(KEY)
    hook = _hook()
    ctx = _run(["read_file", "advisor", "write_file"])
    await hook.before_run(ctx)
    await hook.after_run(ctx)
    injected = _hook({"injected_event": "coworker", "coworker_kind": "advisor_review"})
    await injected.after_run(_run(["write_file", "exec", "exec"]))
    assert env.bus.inbound == []
    assert advisor_state.effective(env.sessions.get_or_create(KEY)) is not None


@pytest.mark.asyncio
async def test_workflow_start_turn_injects_the_first_step(env) -> None:
    wf = env.workspace / "workflows" / "one"
    (wf / "steps").mkdir(parents=True)
    (wf / "workflow.md").write_text('---\nstart: "[[only]]"\n---\n')
    (wf / "steps" / "only.md").write_text("---\ntype: end\n---\nSay hi.\n")
    session = env.sessions.get_or_create(KEY)
    drive.start(session, env.workspace, "one", "")
    await _hook().after_run(_run(["workflow_run"]))
    step = env.bus.inbound[-1]
    assert step.content.startswith("[auto-workflow:one:only]")
    assert step.metadata["workflow_step"] == "only"

    await _hook(step.metadata).after_run(_run([]))
    assert env.bus.outbound[-1].content.startswith("✅ Workflow one finished")


@pytest.mark.asyncio
async def test_room_run_starts_when_the_coordinator_delegated(env) -> None:
    env.configure(CoworkerConfig(room=RoomConfig(agents=[RoomAgentConfig(id="researcher")])))

    class Subagents:
        async def run_inline(self, **kwargs):
            return "facts"

    env.subagents = Subagents()
    env.bind()
    session = env.sessions.get_or_create(KEY)
    scheduler.set_armed(session, True)
    scheduler.record_delegation(KEY, "researcher", "find facts", by="owner", runtime=SimpleNamespace())
    await _hook().after_run(_run(["room_delegate"]))
    await scheduler._room(KEY).task
    assert env.bus.inbound[-1].content.startswith("[auto-room]")


CODING_RESULT_META = {"injected_event": "coworker", "coworker_kind": "coding_result"}


def _strong_advisor(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    monkeypatch.setattr("nanobot.coworker.runtime.runtime_for_preset",
                        lambda preset: SimpleNamespace(model="strong-model"))
    env.sessions.get_or_create(KEY)


@pytest.mark.asyncio
async def test_coding_result_turn_nudges_a_diff_review(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    # Only reading the result: no state-changing steps, yet a review is due.
    await _hook(CODING_RESULT_META).after_run(_run(["coding_agent"]))
    assert len(env.bus.inbound) == 1
    nudge = env.bus.inbound[0]
    assert nudge.content.startswith(ADVISOR_REVIEW_MARKER)
    assert 'action="diff"' in nudge.content and "advisor(" in nudge.content
    assert nudge.metadata["coworker_kind"] == "advisor_review"


@pytest.mark.asyncio
async def test_coding_result_turn_does_not_nudge_when_already_consulted(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    await _hook(CODING_RESULT_META).after_run(_run(["coding_agent", "advisor"]))
    assert env.bus.inbound == []


@pytest.mark.asyncio
async def test_coding_result_nudge_respects_budget_and_the_review_turn_never_loops(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", max_uses=1)))
    monkeypatch.setattr("nanobot.coworker.runtime.runtime_for_preset",
                        lambda preset: SimpleNamespace(model="strong-model"))
    session = env.sessions.get_or_create(KEY)
    advisor_state.count_use(session)  # budget spent
    await _hook(CODING_RESULT_META).after_run(_run(["coding_agent"]))
    assert env.bus.inbound == []

    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    review = _hook({"injected_event": "coworker", "coworker_kind": "advisor_review"})
    await review.after_run(_run(["coding_agent"]))
    assert env.bus.inbound == []


@pytest.mark.asyncio
async def test_coordinator_turn_is_tracked_while_running(env) -> None:
    from nanobot.coworker.runtime import turn_running_since

    env.sessions.get_or_create(KEY)
    hook = _hook()
    assert turn_running_since(KEY) is None
    await hook.before_run(_run([]))
    assert turn_running_since(KEY) is not None
    await hook.on_finally(_run([]))
    assert turn_running_since(KEY) is None
