"""Mechanical stuck detection tests."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.agent.tools.base import ToolResult
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.stuck import StuckTracker, failure_signature
from nanobot.coworker.config import AdvisorConfig, CoworkerConfig
from nanobot.coworker.hook import CoworkerHook
from nanobot.providers.base import ToolCallRequest

KEY = "cli:direct"


def test_failure_signature_normalization() -> None:
    # 1. Non-error returns None
    assert failure_signature("read_file", {"path": "test.txt"}, "file contents here") is None
    assert failure_signature("read_file", {"path": "test.txt"}, ToolResult(content="ok", is_error=False)) is None

    # 2. Error normalization: removes timestamp, hex, path, number, whitespace
    raw_error = (
        "2026-03-30T10:00:00.123456 Error at 0x7fff4a20 in /var/log/app.log: "
        "process 42 terminated with signal 9"
    )
    sig = failure_signature("my_tool", {}, ToolResult(content=raw_error, is_error=True))
    assert sig is not None
    assert "2026" not in sig
    assert "0x7fff4a20" not in sig
    assert "/var/log/app.log" not in sig
    assert "42" not in sig
    assert sig == "my_tool:Error at in : process terminated with signal"

    # 3. BaseException support
    exc = RuntimeError("failure at /tmp/test.txt on thread 100")
    sig_exc = failure_signature("fetch", {}, exc)
    assert sig_exc is not None
    assert sig_exc.startswith("fetch:RuntimeError: failure at on thread")

    # 4. Long errors are truncated to 160 chars
    long_msg = "error: " + "abc" * 100
    sig_long = failure_signature("tool", {}, ToolResult(content=long_msg, is_error=True))
    assert sig_long is not None
    assert len(sig_long) <= 160


def test_failure_signature_exec_exit_codes() -> None:
    # Exit code 0 is never an error
    assert failure_signature("exec", {"command": "pytest"}, "Ran 5 tests\nExit code: 0") is None
    assert failure_signature("exec_session", {"cmd": "ls -la"}, "Exit code: 0\ntotal 0") is None

    # Exit code non-zero is an error
    sig1 = failure_signature("exec", {"command": "npm   test  --run"}, "Tests failed!\nExit code: 1")
    assert sig1 == "exec:npm test --run"

    sig2 = failure_signature("exec_session", {"cmd": "cat /nonexistent"}, "No such file\nExit code: 2")
    assert sig2 == "exec:cat /nonexistent"


def test_stuck_tracker_repeat_and_reset() -> None:
    tracker = StuckTracker()
    sig = "exec:pytest"

    # None is ignored
    assert not tracker.record(None)

    # 1st failure: returns False
    assert not tracker.record(sig)

    # 2nd failure: triggers True
    assert tracker.record(sig)

    # 3rd failure: returns False (only triggers on 2nd)
    assert not tracker.record(sig)

    # Different signature tracks independently
    other_sig = "exec:cargo test"
    assert not tracker.record(other_sig)
    assert tracker.record(other_sig)

    # Reset clears counts
    tracker.reset()
    assert not tracker.record(sig)
    assert tracker.record(sig)


@pytest.mark.asyncio
async def test_hook_stuck_detection_lifecycle(env) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", stuck_detection=True)))
    session = env.sessions.get_or_create(KEY)

    turn_ctx = AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    hook = CoworkerHook(turn_ctx)
    agent_ctx = AgentHookContext(iteration=0, messages=[])

    call1 = ToolCallRequest(id="call_1", name="exec", arguments={"command": "pytest"})
    call2 = ToolCallRequest(id="call_2", name="exec", arguments={"command": "pytest"})

    # 1st failure
    await hook.after_execute_tool(
        agent_ctx, call1, None, call1.arguments, "Tests failed!\nExit code: 1"
    )
    assert "call_1" not in advisor_state.stuck_ids(session)

    # 2nd failure -> repeats signature -> recorded in stuck_ids
    await hook.after_execute_tool(
        agent_ctx, call2, None, call2.arguments, "Tests failed!\nExit code: 1"
    )
    assert "call_2" in advisor_state.stuck_ids(session)

    # Running advisor tool resets tracker
    advisor_call = ToolCallRequest(id="call_adv", name="advisor", arguments={"focus": "help"})
    await hook.after_execute_tool(agent_ctx, advisor_call, None, advisor_call.arguments, "advice")

    # Next failure is 1st again
    call3 = ToolCallRequest(id="call_3", name="exec", arguments={"command": "pytest"})
    await hook.after_execute_tool(
        agent_ctx, call3, None, call3.arguments, "Tests failed!\nExit code: 1"
    )
    assert "call_3" not in advisor_state.stuck_ids(session)


@pytest.mark.asyncio
async def test_hook_stuck_detection_disabled_or_brainstorm(env) -> None:
    # Disabled by config
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", stuck_detection=False)))
    session = env.sessions.get_or_create(KEY)

    turn_ctx = AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    hook = CoworkerHook(turn_ctx)
    agent_ctx = AgentHookContext(iteration=0, messages=[])

    call1 = ToolCallRequest(id="call_1", name="exec", arguments={"command": "pytest"})
    call2 = ToolCallRequest(id="call_2", name="exec", arguments={"command": "pytest"})

    await hook.after_execute_tool(agent_ctx, call1, None, call1.arguments, "Exit code: 1")
    await hook.after_execute_tool(agent_ctx, call2, None, call2.arguments, "Exit code: 1")
    assert not advisor_state.stuck_ids(session)

    # In brainstorm mode, stuck detection is inactive
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", stuck_detection=True)))
    advisor_state.set_mode(session, advisor_state.MODE_BRAINSTORM)
    await hook.after_execute_tool(agent_ctx, call1, None, call1.arguments, "Exit code: 1")
    await hook.after_execute_tool(agent_ctx, call2, None, call2.arguments, "Exit code: 1")
    assert not advisor_state.stuck_ids(session)


def test_transform_request_annotates_stuck_and_is_idempotent(env) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", stuck_detection=True)))
    session = env.sessions.get_or_create(KEY)
    advisor_state.add_stuck_id(session, "call_failed_2")

    turn_ctx = AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    hook = CoworkerHook(turn_ctx)
    agent_ctx = AgentHookContext(iteration=0, messages=[])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "fix bug"},
        {"role": "tool", "tool_call_id": "call_ok_1", "content": "Success"},
        {"role": "tool", "tool_call_id": "call_failed_2", "content": "Exit code: 1"},
    ]

    out_msgs1, _ = hook.transform_request(agent_ctx, messages, None, stateful=False)
    tool_msg = out_msgs1[3]
    assert tool_msg["tool_call_id"] == "call_failed_2"
    assert "Exit code: 1" in tool_msg["content"]
    assert "same failure as an earlier attempt — call advisor" in tool_msg["content"]

    # Other tool message untouched
    assert out_msgs1[2]["content"] == "Success"

    # Idempotence: running transform_request again does not duplicate the annotation
    out_msgs2, _ = hook.transform_request(agent_ctx, out_msgs1, None, stateful=False)
    assert out_msgs2[3]["content"] == tool_msg["content"]
    assert out_msgs2[3]["content"].count("same failure as an earlier attempt") == 1


def test_transform_request_no_annotation_when_advisor_off(env) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset=None)))  # Advisor off
    session = env.sessions.get_or_create(KEY)
    advisor_state.add_stuck_id(session, "call_failed_2")

    turn_ctx = AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY)
    hook = CoworkerHook(turn_ctx)
    agent_ctx = AgentHookContext(iteration=0, messages=[])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "fix bug"},
        {"role": "tool", "tool_call_id": "call_failed_2", "content": "Exit code: 1"},
    ]

    out_msgs, _ = hook.transform_request(agent_ctx, messages, None, stateful=False)
    assert out_msgs[2]["content"] == "Exit code: 1"
