"""Tests for the pilot provider/model circuit registry."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nanobot.config.schema import Config, ModelPresetConfig
from nanobot.pilot.routing import RoutingInput, route_turn
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.fallback_provider import FallbackProvider


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _key(provider: str = "primary", model: str = "model-a") -> Any:
    from nanobot.pilot.circuit import CircuitKey

    return CircuitKey(provider, model)


def _registry(clock: FakeClock, *, threshold: int = 3, cooldown: float = 30.0) -> Any:
    from nanobot.pilot.circuit import CircuitRegistry

    return CircuitRegistry(clock, failure_threshold=threshold, cooldown_seconds=cooldown)


def test_circuit_closes_after_successful_half_open_probe() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=2)
    key = _key()

    registry.record_failure(key, "server_error")
    registry.record_failure(key, "server_error")
    assert registry.allow(key) is False

    clock.advance(30)
    assert registry.allow(key) is True
    registry.record_success(key)

    assert registry.allow(key) is True
    assert registry.snapshot()[key]["state"] == "closed"


def test_circuits_are_isolated_by_provider_and_model() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=1)
    failed_key = _key("primary", "model-a")

    registry.record_failure(failed_key, "server_error")

    assert registry.allow(failed_key) is False
    assert registry.allow(_key("primary", "model-b")) is True
    assert registry.allow(_key("backup", "model-a")) is True


def test_only_one_half_open_probe_is_admitted() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=1)
    key = _key()
    registry.record_failure(key, "timeout")
    clock.advance(30)

    assert registry.allow(key) is True
    assert registry.allow(key) is False


def test_retryable_failures_open_at_the_configured_threshold() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=3)
    key = _key()

    registry.record_failure(key, "server_error")
    registry.record_failure(key, "server_error")
    assert registry.allow(key) is True

    registry.record_failure(key, "server_error")
    assert registry.allow(key) is False


def test_cooldown_reopens_the_circuit_for_a_probe() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=1, cooldown=10)
    key = _key()
    registry.record_failure(key, "rate_limit")

    clock.advance(9.9)
    assert registry.allow(key) is False
    clock.advance(0.1)
    assert registry.allow(key) is True


def test_authentication_failure_opens_immediately() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=99)
    key = _key()

    registry.record_failure(key, "authentication")

    assert registry.allow(key) is False


def test_router_omits_a_preset_with_an_open_provider_model_circuit() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=1)
    config = Config.model_validate({
        "modelPresets": {
            "fast": {"provider": "primary", "model": "model-a"},
            "backup": {"provider": "backup", "model": "model-b"},
            "tools": {"provider": "tools", "model": "model-tools"},
        },
        "pilot": {
            "enabled": True,
            "routing": {
                "enabled": True,
                "default": {"preset": "fast"},
                "reasoning": {"preset": "backup"},
                "toolHeavy": {"preset": "tools"},
                "fallbacks": ["backup"],
            },
        },
    })
    registry.record_failure(_key("primary", "model-a"), "server_error")

    decision = route_turn("turn-1", RoutingInput(channel="test", content="hello"), config, registry)

    assert decision.primary_preset == "backup"
    assert decision.fallback_presets == ()


class _FailingProvider(LLMProvider):
    provider_alias = "primary"

    def get_default_model(self) -> str:
        return "model-a"

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.calls = getattr(self, "calls", 0) + 1
        return LLMResponse(content="provider internal details", finish_reason="error", error_kind="server_error")


def _fallback(model: str, provider: str) -> ModelPresetConfig:
    return ModelPresetConfig(model=model, provider=provider)


@pytest.mark.asyncio
async def test_all_open_candidates_return_a_generic_error_without_provider_aliases() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=1)
    primary = _FailingProvider()
    fallback = _fallback("model-b", "backup")
    registry.record_failure(_key("primary", "model-a"), "server_error")
    registry.record_failure(_key("backup", "model-b"), "server_error")

    result = await FallbackProvider(
        primary=primary,
        fallback_presets=[fallback],
        provider_factory=MagicMock(),
        circuit=registry,
    ).chat(messages=[])

    assert result.finish_reason == "error"
    assert result.content == "The requested model is temporarily unavailable. Please try again later."
    assert "primary" not in result.content
    assert "backup" not in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        LLMResponse(content="unauthorized", finish_reason="error", error_kind="http", error_status_code=401),
        LLMResponse(
            content="bad key",
            finish_reason="error",
            error_type="invalid_request_error",
            error_code="invalid_api_key",
        ),
    ],
)
async def test_authentication_metadata_opens_a_provider_circuit_immediately(response: LLMResponse) -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=99)
    primary = _FailingProvider()

    async def _response(**kwargs: Any) -> LLMResponse:
        primary.calls = getattr(primary, "calls", 0) + 1
        return response

    primary.chat = _response  # type: ignore[method-assign]
    provider = FallbackProvider(primary, [], MagicMock(), circuit=registry)

    await provider.chat(messages=[])
    await provider.chat(messages=[])

    assert primary.calls == 1


@pytest.mark.asyncio
async def test_non_fallbackable_errors_do_not_open_a_provider_circuit() -> None:
    clock = FakeClock()
    registry = _registry(clock, threshold=2)
    primary = _FailingProvider()
    response = LLMResponse(content="invalid request", finish_reason="error", error_kind="invalid_request")

    async def _response(**kwargs: Any) -> LLMResponse:
        primary.calls = getattr(primary, "calls", 0) + 1
        return response

    primary.chat = _response  # type: ignore[method-assign]
    provider = FallbackProvider(primary, [], MagicMock(), circuit=registry)

    await provider.chat(messages=[])
    await provider.chat(messages=[])
    await provider.chat(messages=[])

    assert primary.calls == 3
