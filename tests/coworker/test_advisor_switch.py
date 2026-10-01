"""Manual advisor switch, brainstorm mode, @mention routing notes and provider cache metrics."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.coworker import runtime
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import BRAINSTORM_SYSTEM_PROMPT
from nanobot.coworker.advisor.tool import AdvisorTool
from nanobot.coworker.config import (
    AdvisorConfig,
    CodingAgentConfig,
    CoworkerConfig,
    RoomAgentConfig,
    RoomConfig,
)
from nanobot.coworker.context import metrics
from nanobot.coworker.hook import CoworkerHook
from nanobot.coworker.status import coworker_session_status
from nanobot.providers.base import LLMResponse, LLMUsage

KEY = "cli:direct"


def _runtime(content: str = "consider option B") -> SimpleNamespace:
    provider = SimpleNamespace(
        chat_with_retry=AsyncMock(return_value=LLMResponse(content=content, finish_reason="stop"))
    )
    return SimpleNamespace(provider=provider, model="strong-model")


def _hook() -> CoworkerHook:
    return CoworkerHook(AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY, metadata={}))


def _transform(user: str):
    return _hook().transform_request(
        AgentHookContext(iteration=0, messages=[]),
        [{"role": "system", "content": "BASE"}, {"role": "user", "content": user}],
        None,
        stateful=False,
    )


# ---------- manual switch ----------

def test_switch_on_needs_a_preset_and_off_overrides_the_global_default(env) -> None:
    session = env.sessions.get_or_create(KEY)
    with pytest.raises(ValueError, match="no advisor preset"):
        advisor_state.apply_switch(session, enabled=True)
    assert advisor_state.effective(session) is None

    eff = advisor_state.apply_switch(session, enabled=True, preset="strong", mode="brainstorm")
    assert eff is not None and eff.preset == "strong" and eff.mode == "brainstorm"

    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="global")))
    assert advisor_state.apply_switch(session, enabled=False) is None  # beats the global preset
    back = advisor_state.apply_switch(session, enabled=True)
    assert back is not None and back.preset == "global"


def test_switch_rejects_unknown_mode_and_off_preset(env) -> None:
    session = env.sessions.get_or_create(KEY)
    with pytest.raises(ValueError):
        advisor_state.apply_switch(session, mode="poetry")
    with pytest.raises(ValueError):
        advisor_state.apply_switch(session, enabled=True, preset="off")


# ---------- brainstorm mode ----------

@pytest.mark.asyncio
async def test_brainstorm_consults_without_evidence_and_logs_the_exchange(env, monkeypatch) -> None:
    rt = _runtime()
    monkeypatch.setattr("nanobot.coworker.advisor.tool.runtime_for_preset", lambda preset: rt)
    session = env.sessions.get_or_create(KEY)
    advisor_state.apply_switch(session, enabled=True, preset="strong", mode="brainstorm")
    runtime.remember_live_messages(KEY, [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}])
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key=KEY)):
        result = await AdvisorTool().execute(focus="A or B?")
    assert result.startswith("ADVISOR (strong-model) — advice 1/10")  # no insufficient_context refusal
    sent = rt.provider.chat_with_retry.await_args.kwargs["messages"]
    assert sent[0]["content"] == BRAINSTORM_SYSTEM_PROMPT
    [entry] = advisor_state.history(session)
    assert entry["focus"] == "A or B?" and entry["advice"] == "consider option B"
    assert entry["mode"] == "brainstorm"


def test_history_is_bounded(env) -> None:
    session = env.sessions.get_or_create(KEY)
    total = advisor_state.HISTORY_LIMIT + 3
    for i in range(total):
        advisor_state.record_exchange(session, model="m", focus=f"q{i}", advice="a", mode="coding", now=float(i))
    hist = advisor_state.history(session)
    assert len(hist) == advisor_state.HISTORY_LIMIT and hist[-1]["focus"] == f"q{total - 1}"


def test_brainstorm_swaps_the_directive(env) -> None:
    session = env.sessions.get_or_create(KEY)
    advisor_state.apply_switch(session, enabled=True, preset="strong", mode="brainstorm")
    system = _transform("what should our pricing be?")[0][0]["content"]
    assert "## Advisor (brainstorm mode)" in system and "ORIENT" not in system
    advisor_state.apply_switch(session, mode="coding")
    assert "ORIENT" in _transform("what should our pricing be?")[0][0]["content"]


# ---------- @mentions ----------

def test_at_agy_annotates_only_that_user_message(env) -> None:
    env.configure(CoworkerConfig(coding=CodingAgentConfig(enabled=True)))
    env.sessions.get_or_create(KEY)
    user = _transform("@agy fix the failing login test")[0][1]["content"]
    assert user.startswith("@agy fix the failing login test")
    assert "backend='agy'" in user and "coding_agent(action='start'" in user
    assert _transform("no mention here")[0][1]["content"] == "no mention here"
    assert _transform("mail me at a@agy.com")[0][1]["content"] == "mail me at a@agy.com"


def test_at_agy_says_so_when_coding_is_disabled(env) -> None:
    env.sessions.get_or_create(KEY)
    assert "coding agents are disabled" in _transform("@agy refactor auth")[0][1]["content"]


def test_room_agent_with_the_same_id_is_left_to_the_room(env) -> None:
    env.configure(CoworkerConfig(
        coding=CodingAgentConfig(enabled=True),
        room=RoomConfig(agents=[RoomAgentConfig(id="agy", backend="agy")]),
    ))
    env.sessions.get_or_create(KEY)
    assert _transform("@agy do it")[0][1]["content"] == "@agy do it"


def test_at_advisor_follows_the_switch(env) -> None:
    session = env.sessions.get_or_create(KEY)
    assert "switched off" in _transform("@advisor thoughts?")[0][1]["content"]
    advisor_state.apply_switch(session, enabled=True, preset="strong")
    assert "Call the advisor tool now" in _transform("@advisor thoughts?")[0][1]["content"]


def test_annotation_is_byte_stable_across_requests(env) -> None:
    env.configure(CoworkerConfig(coding=CodingAgentConfig(enabled=True)))
    env.sessions.get_or_create(KEY)
    assert _transform("@pi add a test")[0][1]["content"] == _transform("@pi add a test")[0][1]["content"]


# ---------- provider cache metrics ----------

def test_metrics_aggregate_reported_cache_and_ignore_unreported() -> None:
    metrics.reset()
    metrics.record(KEY, LLMUsage.reported(input_tokens=1000, output_tokens=50, cache_read_tokens=0, cache_write_tokens=900))
    metrics.record(KEY, LLMUsage.reported(input_tokens=1000, output_tokens=40, cache_read_tokens=900, cache_write_tokens=0))
    metrics.record(KEY, LLMUsage.reported(input_tokens=500, output_tokens=10))  # provider reports no cache fields
    snap = metrics.snapshot(KEY)
    assert snap["calls"] == 3 and snap["reported"] is True
    assert snap["cache_read_tokens"] == 900 and snap["cache_write_tokens"] == 900
    assert snap["hit_rate"] == pytest.approx(900 / 2000)  # the unreported call is not counted as a miss
    assert snap["last"]["hit_rate"] is None
    assert snap["recent_hit_rates"] == [0.0, 0.9, None]
    assert metrics.snapshot("other")["calls"] == 0 and metrics.snapshot("other")["hit_rate"] is None


@pytest.mark.asyncio
async def test_hook_records_usage_and_status_exposes_it(env) -> None:
    metrics.reset()
    usage = LLMUsage.reported(input_tokens=2000, output_tokens=20, cache_read_tokens=1500, cache_write_tokens=100)
    await _hook().after_iteration(AgentHookContext(iteration=0, messages=[], usage=usage))
    status = coworker_session_status(env.sessions.get_or_create(KEY))
    assert status["caching"]["usage"]["hit_rate"] == pytest.approx(0.75)
    assert status["advisor"]["mode"] == "coding" and status["advisor"]["history"] == []


def test_status_lists_mentions(env) -> None:
    env.configure(CoworkerConfig(
        coding=CodingAgentConfig(enabled=True),
        room=RoomConfig(agents=[RoomAgentConfig(id="writer", name="Writer", bio="copy")]),
    ))
    session = env.sessions.get_or_create(KEY)
    advisor_state.apply_switch(session, enabled=True, preset="strong")
    status = coworker_session_status(session)
    mentions = {m["id"]: m for m in status["mentions"]}
    assert mentions["writer"]["kind"] == "teammate"
    assert mentions["agy"]["kind"] == "coding" and mentions["agy"]["enabled"] is True
    assert mentions["advisor"]["enabled"] is True
    json.dumps(status)


# ---------- HTTP mutation ----------

def _call_switch(env, payload: dict, *, mutation: bool = True):
    import asyncio

    from nanobot.webui import ws_http

    request = SimpleNamespace(path="/x")
    setattr(request, ws_http._WEBUI_MUTATION_REQUEST_ATTR, mutation)
    setattr(request, ws_http._WEBUI_MUTATION_PAYLOAD_ATTR, payload)
    fake = SimpleNamespace(check_api_token=lambda _r: True, session_manager=env.sessions)
    return asyncio.run(ws_http.GatewayHTTPHandler._handle_session_coworker_advisor(fake, request, "websocket:abc"))


def test_mutation_route_switches_the_live_session_and_returns_status(env) -> None:
    response = _call_switch(env, {"enabled": True, "preset": "strong", "mode": "brainstorm"})
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["advisor"]["enabled"] is True and body["advisor"]["mode"] == "brainstorm"
    assert body["advisor"]["preset"] == "strong"
    # persisted, so it survives a reload of the session
    assert advisor_state.effective(env.sessions.get_or_create("websocket:abc")).preset == "strong"

    off = json.loads(_call_switch(env, {"enabled": False}).body)
    assert off["advisor"]["enabled"] is False and off["advisor"]["mode"] == "brainstorm"


def test_mutation_route_validates_input(env) -> None:
    assert _call_switch(env, {"enabled": True}).status_code == 400  # no preset anywhere
    assert _call_switch(env, {"enabled": "yes"}).status_code == 400
    assert _call_switch(env, {"mode": "poetry"}).status_code == 400
    assert _call_switch(env, {"enabled": False}, mutation=False).status_code == 405


def test_mutation_action_maps_to_the_session_path() -> None:
    from nanobot.webui.ws_http import GatewayHTTPHandler

    path = GatewayHTTPHandler._webui_mutation_path("session.coworker.advisor", {"key": "websocket:abc"})
    assert path == "/api/sessions/websocket%3Aabc/coworker/advisor"


def test_mutation_route_resets_uses(env) -> None:
    session = env.sessions.get_or_create("websocket:abc")
    advisor_state.apply_switch(session, enabled=True, preset="strong")
    advisor_state.count_use(session)
    advisor_state.count_use(session)
    assert advisor_state.effective(session).uses == 2

    resp = _call_switch(env, {"reset_uses": True})
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["advisor"]["uses"] == 0
    assert advisor_state.effective(session).uses == 0


@pytest.mark.asyncio
async def test_cmd_advisor_reset(env) -> None:
    from nanobot.bus.events import InboundMessage
    from nanobot.command.router import CommandContext
    from nanobot.coworker.commands import cmd_advisor

    session = env.sessions.get_or_create("websocket:abc")
    advisor_state.apply_switch(session, enabled=True, preset="strong")
    advisor_state.count_use(session)
    assert advisor_state.effective(session).uses == 1

    msg = InboundMessage(channel="websocket", sender_id="u1", chat_id="abc", content="/advisor reset")
    loop = SimpleNamespace(sessions=env.sessions)
    ctx = CommandContext(msg=msg, key="websocket:abc", args="reset", raw="/advisor reset", loop=loop, session=session)
    reply = await cmd_advisor(ctx)
    assert "0/" in reply.content
    assert advisor_state.effective(session).uses == 0
