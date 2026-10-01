"""Tests for per-session context auto-optimize and cold-cache latching (D12)."""

from __future__ import annotations

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.coworker import directives
from nanobot.coworker.config import ContextConfig, CoworkerConfig
from nanobot.coworker.context import optimizer
from nanobot.coworker.hook import WASTED_TOOL, CoworkerHook
from nanobot.coworker.runtime import session_state
from nanobot.coworker.session_api import apply_context
from nanobot.coworker.status import coworker_session_status

KEY = "cli:opt_session"


@pytest.fixture(autouse=True)
def clean_state():
    optimizer.reset_states()
    yield
    optimizer.reset_states()


def test_resolve_latched_holds_value_while_warm(env) -> None:
    session = env.sessions.get_or_create(KEY)

    # 1. Cold start adopts global setting
    latch, pending, source = optimizer.resolve_latched(
        session,
        cold=True,
        cfg_optimize=False,
        cfg_trim=False,
    )
    assert latch.optimize is False
    assert latch.trim is False
    assert pending is False
    assert source == "global"

    # 2. Session override requested: apply_context
    apply_context(session, {"optimize": True})
    assert session_state(session)["context"]["optimize"] is True

    # 3. While warm, resolve_latched retains previous latch
    warm_latch, warm_pending, warm_source = optimizer.resolve_latched(
        session,
        cold=False,
        cfg_optimize=False,
        cfg_trim=False,
    )
    assert warm_latch.optimize is False  # held back
    assert warm_pending is True  # pending cold
    assert warm_source == "session"

    # 4. Once cold, resolve_latched adopts requested value
    cold_latch, cold_pending, cold_source = optimizer.resolve_latched(
        session,
        cold=True,
        cfg_optimize=False,
        cfg_trim=False,
    )
    assert cold_latch.optimize is True  # adopted
    assert cold_pending is False
    assert cold_source == "session"


def test_hook_respects_latch_while_warm_and_updates_when_cold(env) -> None:
    env.configure(CoworkerConfig(context=ContextConfig(optimize=False)))
    session = env.sessions.get_or_create(KEY)

    hook = CoworkerHook(AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY, metadata={}))
    messages = [
        {"role": "system", "content": "BASE"},
        {"role": "user", "content": "hello"},
    ]
    tools = [{"name": WASTED_TOOL, "description": "mark wasted"}]

    # Turn 1: cold start, optimize is off globally
    out_msgs, out_tools = hook.transform_request(
        AgentHookContext(iteration=0, messages=[]),
        messages,
        tools,
        stateful=False,
    )
    # WASTED directive not added, tool is hidden
    assert not any(directives.WASTED in str(m.get("content")) for m in out_msgs)
    tool_names = [t.get("name") or t.get("function", {}).get("name") for t in (out_tools or [])]
    assert WASTED_TOOL not in tool_names

    # Mark cache warm
    optimizer.touch(KEY)

    # Enable optimize in session while warm
    apply_context(session, {"optimize": True})

    # Turn 2: cache is still warm -> latch should hold optimize OFF
    out_msgs2, out_tools2 = hook.transform_request(
        AgentHookContext(iteration=1, messages=[]),
        messages,
        tools,
        stateful=False,
    )
    assert not any(directives.WASTED in str(m.get("content")) for m in out_msgs2)
    tool_names2 = [t.get("name") or t.get("function", {}).get("name") for t in (out_tools2 or [])]
    assert WASTED_TOOL not in tool_names2

    # Advance time beyond TTL (cache cold)
    opt_state = optimizer.state_for(KEY)
    opt_state.last_send = 1.0  # long ago

    # Turn 3: cache is cold -> latch adopts optimize ON
    out_msgs3, out_tools3 = hook.transform_request(
        AgentHookContext(iteration=2, messages=[]),
        messages,
        tools,
        stateful=False,
    )
    assert any(directives.WASTED in str(m.get("content")) for m in out_msgs3)
    tool_names3 = [t.get("name") or t.get("function", {}).get("name") for t in (out_tools3 or [])]
    assert WASTED_TOOL in tool_names3


def test_status_reports_optimize_fields(env) -> None:
    session = env.sessions.get_or_create(KEY)
    st = coworker_session_status(session)
    opt = st["caching"]["optimize"]
    assert "enabled" in opt
    assert "latched" in opt
    assert "pending" in opt
    assert "source" in opt
    assert "dropped" in opt
    assert "rewritten" in opt
    assert "trimmed" in opt
    assert "saved_messages" in opt
