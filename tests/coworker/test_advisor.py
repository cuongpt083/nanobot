"""Advisor consult + tool: thin-context guard, budget, breaker, clean reviewer prompt."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.coworker import runtime
from nanobot.coworker.advisor import consult
from nanobot.coworker.advisor.consult import ADVISOR_SYSTEM_PROMPT, is_thin_context, run_consult
from nanobot.coworker.advisor.tool import AdvisorTool
from nanobot.coworker.config import AdvisorConfig, CoworkerConfig
from nanobot.providers.base import LLMResponse

EVIDENCE = [
    {"role": "system", "content": "EXECUTOR SYSTEM"},
    {"role": "user", "content": "fix the bug"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "def f(): ..."},
]


def _runtime(content: str = "do X next", finish: str = "stop") -> SimpleNamespace:
    provider = SimpleNamespace(chat_with_retry=AsyncMock(return_value=LLMResponse(content=content, finish_reason=finish)))
    return SimpleNamespace(provider=provider, model="strong-model")


def test_thin_context_is_scoped_to_the_current_run() -> None:
    assert is_thin_context([{"role": "user", "content": "hi"}])
    assert not is_thin_context(EVIDENCE)


def test_transcript_budget_keeps_task_and_newest_tail(monkeypatch) -> None:
    monkeypatch.setattr(consult, "TRANSCRIPT_MAX_CHARS", 400)
    messages = [{"role": "user", "content": "THE TASK"}] + [
        {"role": "assistant", "content": f"step {i} " + "x" * 80} for i in range(20)
    ]
    text, dropped = consult.serialize_transcript(messages)
    assert text.startswith("### User\nTHE TASK") and dropped > 0
    assert "step 19" in text and "step 0 " not in text


@pytest.mark.asyncio
async def test_consult_uses_a_clean_reviewer_prompt() -> None:
    rt = _runtime()
    result = await run_consult(messages=EVIDENCE, runtime=rt, focus="is the plan ok?", max_tokens=512,
                               timeout_s=5, allow_thin=False)
    assert result.ok and result.text == "do X next"
    sent = rt.provider.chat_with_retry.await_args.kwargs
    assert sent["tools"] is None and sent["max_tokens"] == 512
    assert sent["messages"][0] == {"role": "system", "content": ADVISOR_SYSTEM_PROMPT}
    user = sent["messages"][1]["content"]
    assert "EXECUTOR SYSTEM" in user and "→ tool call: read_file" in user
    assert "The executor asks specifically: is the plan ok?" in user


@pytest.mark.asyncio
async def test_breaker_opens_after_repeated_failures() -> None:
    rt = _runtime(content="", finish="error")
    for _ in range(2):
        assert not (await run_consult(messages=EVIDENCE, runtime=rt, focus=None, max_tokens=1,
                                      timeout_s=5, allow_thin=True)).ok
    skipped = await run_consult(messages=EVIDENCE, runtime=rt, focus=None, max_tokens=1, timeout_s=5, allow_thin=True)
    assert skipped.code == "advisor_unavailable"
    assert rt.provider.chat_with_retry.await_count == 2


@pytest.mark.asyncio
async def test_tool_refuses_once_then_counts_budget(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", max_uses=1)))
    rt = _runtime()
    monkeypatch.setattr("nanobot.coworker.advisor.tool.runtime_for_preset", lambda preset: rt)
    env.sessions.get_or_create("cli:direct")
    tool = AdvisorTool()
    thin = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
    runtime.remember_live_messages("cli:direct", thin)
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct")):
        first = json.loads(await tool.execute())
        assert first["status"] == "insufficient_context"
        second = await tool.execute(focus="just answer")
        assert second.startswith("ADVISOR (strong-model) — advice 1/1")
        third = json.loads(await tool.execute())
        assert third["status"] == "max_uses_exceeded"
    assert rt.provider.chat_with_retry.await_count == 1


@pytest.mark.asyncio
async def test_tool_reports_disabled_without_a_preset(env) -> None:
    env.sessions.get_or_create("cli:direct")
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key="cli:direct")):
        result = json.loads(await AdvisorTool().execute())
    assert result["status"] == "advisor_disabled"
