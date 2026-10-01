"""CoworkerHook: per-session tool visibility, directives, and the in-run advisor nudge."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.agent.hook import AgentHookContext, AgentRunHookContext, AgentTurnHookContext
from nanobot.coworker.advisor import policy
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.config import AdvisorConfig, CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.hook import CoworkerHook
from nanobot.coworker.room import scheduler
from nanobot.coworker.workflows import drive

KEY = "cli:direct"
ALL_TOOLS = [
    {"type": "function", "function": {"name": n}}
    for n in ("read_file", "advisor", "room_delegate", "room_state", "agents_list",
              "mark_context_wasted", "workflow_run", "workflow_distill")
]


def _hook(metadata: dict | None = None, *, key: str = KEY) -> CoworkerHook:
    return CoworkerHook(AgentTurnHookContext(channel="cli", chat_id="direct", session_key=key,
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


# ---------- advisor review nudge (in-run continuation) ----------

def _tool_messages(*names: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "build it"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": name}}
            for i, name in enumerate(names)
        ]},
    ]


def _strong_advisor(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    monkeypatch.setattr(
        "nanobot.coworker.hook.runtime_for_preset",
        lambda preset: SimpleNamespace(model="strong-model"),
    )
    env.sessions.get_or_create(KEY)


async def _prime(hook: CoworkerHook, messages: list[dict[str, Any]], *, iteration: int = 0) -> None:
    await hook.before_run(AgentRunHookContext(messages=[{"role": "user", "content": "build it"}]))
    await hook.before_iteration(AgentHookContext(iteration=iteration, messages=messages))


@pytest.mark.asyncio
async def test_review_nudge_fires_once_in_run_and_never_injects_a_bus_turn(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    hook = _hook()
    await _prime(hook, _tool_messages("write_file", "write_file"))
    text = hook.continuation()
    assert text is not None and text.startswith(policy.ADVISOR_REVIEW_MARKER)
    assert env.bus.inbound == []  # in-run now, not a new turn through the bus
    assert hook.continuation() is None  # latched for the rest of the run
    session = env.sessions.get_or_create(KEY)
    assert advisor_state.review_nudge(session)["kind"] == "first"


@pytest.mark.asyncio
async def test_review_nudge_reconsults_after_a_consult(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    hook = _hook()
    await _prime(hook, _tool_messages("advisor", *(["write_file"] * 12)))
    text = hook.continuation()
    assert text is not None and "(12 steps)" in text
    session = env.sessions.get_or_create(KEY)
    assert advisor_state.review_nudge(session)["kind"] == "reconsult"


@pytest.mark.asyncio
async def test_no_nudge_when_the_advisor_is_off(env) -> None:
    env.sessions.get_or_create(KEY)
    hook = _hook()
    await _prime(hook, _tool_messages("write_file", "write_file"))
    assert hook.continuation() is None


@pytest.mark.asyncio
async def test_no_nudge_when_the_budget_is_spent(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", max_uses=1)))
    monkeypatch.setattr(
        "nanobot.coworker.hook.runtime_for_preset",
        lambda preset: SimpleNamespace(model="strong-model"),
    )
    session = env.sessions.get_or_create(KEY)
    advisor_state.count_use(session)
    hook = _hook()
    await _prime(hook, _tool_messages("write_file", "write_file"))
    assert hook.continuation() is None


@pytest.mark.asyncio
async def test_no_nudge_when_the_breaker_is_open(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    monkeypatch.setattr("nanobot.coworker.hook.breaker_open_seconds", lambda model: 120.0)
    hook = _hook()
    await _prime(hook, _tool_messages("write_file", "write_file"))
    assert hook.continuation() is None


@pytest.mark.asyncio
async def test_no_nudge_on_automated_or_other_injected_turns(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    cron = _hook(key="cron:job")
    await _prime(cron, _tool_messages("write_file", "write_file"))
    assert cron.continuation() is None

    step = _hook({"injected_event": "coworker", "coworker_kind": drive.KIND_WORKFLOW_STEP})
    await _prime(step, _tool_messages("write_file", "write_file"))
    assert step.continuation() is None


@pytest.mark.asyncio
async def test_no_nudge_near_the_iteration_ceiling(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    monkeypatch.setattr("nanobot.coworker.hook._max_tool_iterations", lambda: 10)
    messages = _tool_messages("write_file", "write_file")
    near = _hook()
    await _prime(near, messages, iteration=8)  # 10 - 2
    assert near.continuation() is None
    early = _hook()
    await _prime(early, messages, iteration=0)
    assert early.continuation() is not None


CODING_RESULT_META = {"injected_event": "coworker", "coworker_kind": "coding_result"}


@pytest.mark.asyncio
async def test_coding_result_turn_nudges_a_diff_review(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    hook = _hook(CODING_RESULT_META)
    await _prime(hook, _tool_messages("coding_agent"))
    text = hook.continuation()
    assert text is not None and 'action="diff"' in text and "advisor(" in text


@pytest.mark.asyncio
async def test_coding_result_turn_does_not_nudge_when_already_consulted(env, monkeypatch) -> None:
    _strong_advisor(env, monkeypatch)
    hook = _hook(CODING_RESULT_META)
    await _prime(hook, _tool_messages("coding_agent", "advisor"))
    assert hook.continuation() is None


# ---------- after-run orchestration ----------

def _run(tools_used: list[str], messages=None) -> AgentRunHookContext:
    return AgentRunHookContext(messages=messages or [{"role": "user", "content": "build it"}],
                               final_content="done", tools_used=tools_used, stop_reason="completed")


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
