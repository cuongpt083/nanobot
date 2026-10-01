"""@advisor is user-requested: it bypasses the thin-context refusal for that turn."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.hook import AgentRunHookContext, AgentTurnHookContext
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.coworker import runtime
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.tool import AdvisorTool
from nanobot.coworker.config import AdvisorConfig, CoworkerConfig
from nanobot.coworker.hook import CoworkerHook
from nanobot.providers.base import LLMResponse

KEY = "cli:direct"


def _runtime(content: str = "use Postgres") -> SimpleNamespace:
    provider = SimpleNamespace(
        chat_with_retry=AsyncMock(return_value=LLMResponse(content=content, finish_reason="stop"))
    )
    return SimpleNamespace(provider=provider, model="strong-model")


def _hook() -> CoworkerHook:
    return CoworkerHook(
        AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY, metadata={})
    )


@pytest.mark.asyncio
async def test_user_requested_consult_bypasses_thin_context(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    rt = _runtime()
    monkeypatch.setattr("nanobot.coworker.advisor.tool.runtime_for_preset", lambda preset: rt)
    session = env.sessions.get_or_create(KEY)
    advisor_state.mark_user_request(session)
    runtime.remember_live_messages(KEY, [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}])
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key=KEY)):
        result = await AdvisorTool().execute(focus="Postgres or SQLite?")
    assert result.startswith("ADVISOR (strong-model)")
    assert advisor_state.user_requested(session) is False  # cleared by the successful consult


@pytest.mark.asyncio
async def test_thin_context_is_still_refused_without_the_flag(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    monkeypatch.setattr("nanobot.coworker.advisor.tool.runtime_for_preset", lambda preset: _runtime())
    env.sessions.get_or_create(KEY)
    runtime.remember_live_messages(KEY, [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}])
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key=KEY)):
        result = json.loads(await AdvisorTool().execute())
    assert result["status"] == "insufficient_context"


@pytest.mark.asyncio
async def test_before_run_tracks_the_advisor_mention(env) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong")))
    session = env.sessions.get_or_create(KEY)
    hook = _hook()
    await hook.before_run(
        AgentRunHookContext(messages=[{"role": "user", "content": "@advisor Postgres or SQLite?"}])
    )
    assert advisor_state.user_requested(session) is True
    await hook.before_run(AgentRunHookContext(messages=[{"role": "user", "content": "thanks"}]))
    assert advisor_state.user_requested(session) is False


def test_new_clears_the_user_request_flag(env) -> None:
    session = env.sessions.get_or_create(KEY)
    session.messages.extend([{"role": "user", "content": "hi"}])
    advisor_state.mark_user_request(session)
    assert advisor_state.user_requested(session) is True
    session.messages.clear()  # /new empties the transcript
    assert advisor_state.user_requested(session) is False
