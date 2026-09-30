"""Keep-alive pings must reuse the session cache key and the real request's parameters."""

from __future__ import annotations

import pytest

from nanobot.coworker.context import keepalive
from nanobot.providers.base import LLMProvider, LLMResponse


def _capture(provider: object) -> keepalive._Capture:
    return keepalive._Capture(
        provider=provider,
        model="strong-model",
        messages=[{"role": "system", "content": "BASE"}],
        tools=None,
        max_tokens=4096,
        temperature=0.3,
        reasoning_effort="low",
        real_at=0.0,
    )


@pytest.mark.asyncio
async def test_ping_carries_the_session_id_and_the_real_generation_parameters() -> None:
    recorded: dict[str, object] = {}

    class Provider:
        async def chat_with_context(self, *, provider_context, **kwargs):
            recorded["provider_context"] = provider_context
            recorded["kwargs"] = kwargs
            return LLMResponse(content="ok", finish_reason="stop")

    cap = _capture(Provider())
    response = await keepalive._ping_once(cap, "websocket:abc")

    assert response.content == "ok"
    context = recorded["provider_context"]
    assert getattr(context, "session_id") == "websocket:abc"
    kwargs = recorded["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["model"] == "strong-model"  # D10: identical to the real request
    assert kwargs["max_tokens"] == 4096
    assert kwargs["temperature"] == pytest.approx(0.3)
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["tools"] is None
    assert kwargs["messages"][-1]["content"] == keepalive.PING_PROMPT


@pytest.mark.asyncio
async def test_ping_delegates_when_the_provider_only_implements_chat() -> None:
    """A provider without its own ``chat_with_context`` must still be pingable."""

    class Provider:
        def __init__(self) -> None:
            self.seen: dict[str, object] | None = None

        async def chat(self, **kwargs):
            self.seen = kwargs
            return LLMResponse(content="ok", finish_reason="stop")

        chat_with_context = LLMProvider.chat_with_context

    provider = Provider()
    cap = _capture(provider)
    response = await keepalive._ping_once(cap, "cli:direct")

    assert response.content == "ok"
    assert provider.seen is not None
    assert provider.seen["model"] == "strong-model"
    assert provider.seen["messages"][-1]["content"] == keepalive.PING_PROMPT
