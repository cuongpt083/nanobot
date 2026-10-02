"""CoworkerHook.after_iteration records one durable turn metric per iteration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.coworker.context import optimizer
from nanobot.coworker.hook import CoworkerHook
from nanobot.providers.base import LLMUsage


@pytest.mark.asyncio
async def test_after_iteration_records_turn_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict] = []
    monkeypatch.setattr(
        "nanobot.coworker.hook.metrics_store",
        SimpleNamespace(record_turn=lambda **kw: recorded.append(kw)),
    )

    session = SimpleNamespace(key="s1", metadata={})
    monkeypatch.setattr("nanobot.coworker.hook.get_session", lambda key: session)
    monkeypatch.setattr(
        "nanobot.coworker.hook.services", lambda: SimpleNamespace(workspace=None)
    )

    optimizer.reset_states()
    hook = CoworkerHook(AgentTurnHookContext(session_key="s1"))
    hook._last_runtime = SimpleNamespace(
        provider=SimpleNamespace(provider_name="anthropic", backend="anthropic"),
        model="claude-3-5-sonnet",
    )

    ctx = AgentHookContext(iteration=1, messages=[])
    ctx.usage = LLMUsage.reported(
        input_tokens=100,
        output_tokens=10,
        cache_read_tokens=60,
        cache_write_tokens=5,
    )

    await hook.after_iteration(ctx)

    assert len(recorded) == 1
    entry = recorded[0]
    assert entry["session_key"] == "s1"
    assert entry["provider"] == "anthropic"
    assert entry["model"] == "claude-3-5-sonnet"
    assert entry["usage"] is ctx.usage
    # The turn just refreshed the cache, so it is warm at send time.
    assert entry["warm"] is True
    assert entry["source"] in {"user", "api", "cron", "dream", "system"}
