from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunResult, AgentRunner, AgentRunSpec
from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse, ProviderAttempt
from nanobot.providers.fallback_provider import FallbackProvider
from nanobot.utils.llm_runtime import LLMRuntime


class MockProvider(LLMProvider):

    def __init__(
        self,
        name: str = "mock-provider",
        model: str = "mock-model",
        responses: list[LLMResponse] | None = None,
    ) -> None:
        super().__init__()
        self.provider_alias = name
        self.model = model
        self.responses = list(responses or [])
        self.call_count = 0

    def get_default_model(self) -> str:
        return self.model

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.call_count += 1
        if self.responses:
            res = self.responses.pop(0)
            res.model = self.model  # type: ignore[attr-defined]
            return res
        return LLMResponse(content="OK", finish_reason="stop", usage={"prompt_tokens": 10})

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        return await self.chat(**kwargs)


@pytest.mark.asyncio
async def test_provider_attempts_recorded_on_response() -> None:
    resp1 = LLMResponse(content="transient fail", finish_reason="error", error_kind="timeout")
    resp2 = LLMResponse(
        content="Success response", finish_reason="stop", usage={"prompt_tokens": 12, "completion_tokens": 5}
    )
    provider = MockProvider(name="test-prov", model="test-mod", responses=[resp1, resp2])

    res = await provider.chat_with_retry(messages=[{"role": "user", "content": "hi"}], retry_mode="standard")

    assert res.finish_reason == "stop"
    assert len(res.attempts) == 2

    att1 = res.attempts[0]
    assert att1.provider == "test-prov"
    assert att1.model == "test-mod"
    assert att1.sequence == 1
    assert att1.retry_index == 0
    assert att1.finish_reason == "error"
    assert att1.error_class == "timeout"
    assert "transient fail" not in str(att1)

    att2 = res.attempts[1]
    assert att2.provider == "test-prov"
    assert att2.model == "test-mod"
    assert att2.sequence == 2
    assert att2.retry_index == 1
    assert att2.finish_reason == "stop"
    assert att2.error_class is None
    assert att2.usage == {"prompt_tokens": 12, "completion_tokens": 5}


@pytest.mark.asyncio
async def test_non_retryable_errors_not_retried() -> None:
    non_retryable_cases = [
        LLMResponse(content="Invalid Key", finish_reason="error", error_status_code=401, error_kind="authentication"),
        LLMResponse(content="Bad Params", finish_reason="error", error_status_code=400, error_kind="invalid_request"),
        LLMResponse(content="Blocked", finish_reason="error", error_kind="content_filter"),
        LLMResponse(content="Prompt too long", finish_reason="error", error_kind="context_length"),
    ]

    for err_resp in non_retryable_cases:
        provider = MockProvider(name="test-prov", model="test-mod", responses=[err_resp])
        res = await provider.chat_with_retry(messages=[{"role": "user", "content": "test"}], retry_mode="standard")
        assert provider.call_count == 1
        assert res.finish_reason == "error"
        assert len(res.attempts) == 1


@pytest.mark.asyncio
async def test_fallback_provider_accumulates_attempts() -> None:
    primary_resp = LLMResponse(content="Primary overloaded", finish_reason="error", error_kind="overloaded")
    fallback_resp = LLMResponse(content="Fallback answer", finish_reason="stop", usage={"prompt_tokens": 15})

    primary = MockProvider(name="primary-prov", model="primary-mod", responses=[primary_resp])
    fallback_prov = MockProvider(name="fallback-prov", model="fallback-mod", responses=[fallback_resp])

    fb_preset = MagicMock()
    fb_preset.model = "fallback-mod"
    fb_preset.max_tokens = 100
    fb_preset.temperature = 0.7
    fb_preset.reasoning_effort = None

    fb_provider = FallbackProvider(
        primary=primary,
        fallback_presets=[fb_preset],
        provider_factory=lambda _: fallback_prov,
    )

    res = await fb_provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert res.finish_reason == "stop"
    assert len(res.attempts) == 2
    assert res.attempts[0].provider == "primary-prov"
    assert res.attempts[0].fallback_index == 0
    assert res.attempts[1].provider == "fallback-prov"
    assert res.attempts[1].fallback_index == 1


@pytest.mark.asyncio
async def test_agent_runner_emits_provider_attempts_to_hook() -> None:
    resp = LLMResponse(content="Hello world", finish_reason="stop", usage={"prompt_tokens": 5})
    provider = MockProvider(name="hook-prov", model="hook-mod", responses=[resp])

    observed_attempts: list[ProviderAttempt] = []

    class TestAttemptHook(AgentHook):

        async def on_provider_attempt(
            self,
            context: AgentHookContext,
            attempt: ProviderAttempt,
        ) -> None:
            observed_attempts.append(attempt)

    runner = AgentRunner()
    runtime = LLMRuntime(
        provider=provider,
        model="hook-mod",
        context_window_tokens=8000,
        snapshot_signature=("test",),
        generation=GenerationSettings(max_tokens=4096, temperature=0.7),
    )
    tools = MagicMock()
    tools.get_definitions = MagicMock(return_value=[])

    spec = AgentRunSpec(
        initial_messages=[{"role": "user", "content": "hi"}],
        tools=tools,
        runtime=runtime,
        max_iterations=1,
        max_tool_result_chars=1000,
        hook=TestAttemptHook(),
        session_key="test-session",
    )

    res = await runner.run(spec)
    assert isinstance(res, AgentRunResult)
    assert len(observed_attempts) == 1
    assert observed_attempts[0].provider == "hook-prov"
    assert observed_attempts[0].model == "hook-mod"
