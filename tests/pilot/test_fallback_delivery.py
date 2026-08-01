"""Regression coverage for one-answer fallback delivery."""

from __future__ import annotations

from typing import Any

import pytest

from nanobot.agent.turn_delivery import TurnDeliveryFactory
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.outbound_events import StreamDeltaEvent, StreamedResponseEvent
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import RuntimeEventBus
from nanobot.config.schema import ModelPresetConfig
from nanobot.pilot.circuit import ALL_CANDIDATES_UNAVAILABLE, CircuitKey, CircuitRegistry
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.fallback_provider import FallbackProvider


class _ScriptedProvider(LLMProvider):
    """A provider whose stream deltas and terminal response are controlled separately."""

    def __init__(
        self,
        name: str,
        response: LLMResponse,
        deltas: tuple[str, ...] = (),
        stream_events: tuple[tuple[str, object], ...] = (),
    ) -> None:
        self.name = name
        self.response = response
        self.deltas = deltas
        self.stream_events = stream_events
        self.calls = 0

    @property
    def provider_alias(self) -> str:
        return self.name

    def get_default_model(self) -> str:
        return f"{self.name}-model"

    async def chat(self, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        return self.response

    async def chat_stream(self, **kwargs: Any) -> LLMResponse:
        self.calls += 1
        on_delta = kwargs.get("on_content_delta")
        if on_delta is not None:
            for delta in self.deltas:
                await on_delta(delta)
        for event_name, event_value in self.stream_events:
            callback = kwargs.get(f"on_{event_name}_delta")
            if callback is not None:
                await callback(event_value)
        return self.response


def _preset(model: str, provider: str) -> ModelPresetConfig:
    return ModelPresetConfig(model=model, provider=provider)


async def _deliver(
    provider: FallbackProvider,
    *,
    on_thinking_delta: Any = None,
    on_tool_call_delta: Any = None,
) -> list[OutboundMessage]:
    """Run one streamed provider call through the real turn delivery boundary."""
    bus = MessageBus()
    msg = InboundMessage(
        channel="test",
        sender_id="user",
        chat_id="chat",
        content="hello",
        metadata={"_wants_stream": True},
    )
    delivery = TurnDeliveryFactory(bus, RuntimeEventBus()).create(
        msg,
        msg.session_key,
        enable_stream=True,
    )
    response = await provider.chat_stream(
        messages=[],
        on_content_delta=delivery.on_stream,
        on_stream_recover=delivery.on_stream_end,
        on_thinking_delta=on_thinking_delta,
        on_tool_call_delta=on_tool_call_delta,
    )
    streamed = bus.outbound_size > 0
    if streamed:
        await delivery.on_stream_end()
    await delivery.complete(
        OutboundMessage(
            channel="test",
            chat_id="chat",
            content=response.content or "",
            event=StreamedResponseEvent() if streamed and response.finish_reason != "error" else None,
        ),
        publish_completion=False,
    )
    messages: list[OutboundMessage] = []
    while bus.outbound_size:
        messages.append(await bus.consume_outbound())
    return messages


def _visible_content(messages: list[OutboundMessage]) -> list[str]:
    """Content-bearing messages are the client-visible answer/error segments."""
    return [
        message.content
        for message in messages
        if message.content and isinstance(message.event, StreamDeltaEvent | type(None))
    ]


@pytest.mark.asyncio
async def test_failure_before_stream_delivers_only_the_fallback_answer() -> None:
    primary = _ScriptedProvider(
        "primary", LLMResponse("provider internal", finish_reason="error", error_kind="server_error")
    )
    backup = _ScriptedProvider("backup", LLMResponse("fallback answer"), ("fallback answer",))
    provider = FallbackProvider(primary, [_preset("backup-model", "backup")], lambda _: backup)

    assert _visible_content(await _deliver(provider)) == ["fallback answer"]


@pytest.mark.asyncio
async def test_timeout_after_partial_stream_discards_primary_fragment_before_fallback() -> None:
    primary = _ScriptedProvider(
        "primary",
        LLMResponse("timeout detail", finish_reason="error", error_kind="timeout"),
        ("partial primary",),
    )
    backup = _ScriptedProvider("backup", LLMResponse("fallback answer"), ("fallback answer",))
    provider = FallbackProvider(primary, [_preset("backup-model", "backup")], lambda _: backup)

    assert _visible_content(await _deliver(provider)) == ["fallback answer"]


@pytest.mark.asyncio
async def test_non_timeout_error_after_content_discards_partial_fragment_and_delivers_one_error() -> None:
    primary = _ScriptedProvider(
        "primary",
        LLMResponse("request rejected", finish_reason="error", error_kind="invalid_request"),
        ("partial primary",),
    )
    provider = FallbackProvider(primary, [_preset("backup-model", "backup")], lambda _: None)

    assert _visible_content(await _deliver(provider)) == ["request rejected"]


@pytest.mark.asyncio
async def test_exhausted_chain_delivers_one_fixed_safe_error() -> None:
    primary = _ScriptedProvider(
        "primary", LLMResponse("primary secret", finish_reason="error", error_kind="server_error")
    )
    backup = _ScriptedProvider(
        "backup", LLMResponse("backup secret", finish_reason="error", error_kind="server_error")
    )
    provider = FallbackProvider(primary, [_preset("backup-model", "backup")], lambda _: backup)

    assert _visible_content(await _deliver(provider)) == [ALL_CANDIDATES_UNAVAILABLE]


@pytest.mark.asyncio
async def test_mixed_open_and_unconstructable_fallback_chain_hides_primary_error() -> None:
    circuit = CircuitRegistry(failure_threshold=1)
    circuit.record_failure(CircuitKey("open-backup", "open-model"), "server_error")
    primary = _ScriptedProvider(
        "primary", LLMResponse("primary provider detail", finish_reason="error", error_kind="server_error")
    )

    def _factory(preset: ModelPresetConfig) -> LLMProvider:
        assert preset.model == "factory-model"
        raise ValueError("provider setup detail")

    provider = FallbackProvider(
        primary,
        [
            _preset("open-model", "open-backup"),
            _preset("factory-model", "factory-backup"),
        ],
        _factory,
        circuit=circuit,
    )

    assert _visible_content(await _deliver(provider)) == [ALL_CANDIDATES_UNAVAILABLE]
    assert primary.calls == 1


@pytest.mark.asyncio
async def test_all_open_chain_delivers_one_fixed_safe_error() -> None:
    circuit = CircuitRegistry(failure_threshold=1)
    circuit.record_failure(CircuitKey("primary", "primary-model"), "server_error")
    circuit.record_failure(CircuitKey("backup", "backup-model"), "server_error")
    primary = _ScriptedProvider("primary", LLMResponse("should not run"))
    provider = FallbackProvider(
        primary,
        [_preset("backup-model", "backup")],
        lambda _: None,
        circuit=circuit,
    )

    assert _visible_content(await _deliver(provider)) == [ALL_CANDIDATES_UNAVAILABLE]
    assert primary.calls == 0


@pytest.mark.asyncio
async def test_capture_observer_exception_preserves_fallback_and_one_answer() -> None:
    capture_health_failures = 0

    async def _capture_fallback(_: str) -> None:
        nonlocal capture_health_failures
        capture_health_failures += 1
        raise RuntimeError("capture unavailable")

    primary = _ScriptedProvider(
        "primary", LLMResponse("provider internal", finish_reason="error", error_kind="server_error")
    )
    backup = _ScriptedProvider("backup", LLMResponse("fallback answer"), ("fallback answer",))
    provider = FallbackProvider(
        primary,
        [_preset("backup-model", "backup")],
        lambda _: backup,
        fallback_model_observer=_capture_fallback,
    )

    assert _visible_content(await _deliver(provider)) == ["fallback answer"]
    assert capture_health_failures == 1
    assert primary.calls == backup.calls == 1


@pytest.mark.asyncio
async def test_rejected_candidate_callbacks_are_not_replayed_to_progress_hooks() -> None:
    primary = _ScriptedProvider(
        "primary",
        LLMResponse("timeout detail", finish_reason="error", error_kind="timeout"),
        ("primary-content-canary",),
        (
            ("thinking", "primary-thinking-canary"),
            ("tool_call", {"kind": "primary-tool-canary"}),
        ),
    )
    backup = _ScriptedProvider(
        "backup",
        LLMResponse("fallback answer"),
        ("fallback answer",),
        (
            ("thinking", "fallback-thinking"),
            ("tool_call", {"kind": "fallback-tool"}),
        ),
    )
    provider = FallbackProvider(primary, [_preset("backup-model", "backup")], lambda _: backup)
    replayed: list[tuple[str, object]] = []

    async def _thinking(value: str) -> None:
        replayed.append(("thinking", value))

    async def _tool(value: dict[str, str]) -> None:
        replayed.append(("tool", value))

    messages = await _deliver(
        provider,
        on_thinking_delta=_thinking,
        on_tool_call_delta=_tool,
    )

    assert _visible_content(messages) == ["fallback answer"]
    assert replayed == [
        ("thinking", "fallback-thinking"),
        ("tool", {"kind": "fallback-tool"}),
    ]


@pytest.mark.asyncio
async def test_turn_delivery_ignores_a_second_terminal_completion() -> None:
    bus = MessageBus()
    msg = InboundMessage(channel="test", sender_id="user", chat_id="chat", content="hello")
    delivery = TurnDeliveryFactory(bus, RuntimeEventBus()).create(msg, msg.session_key)

    await delivery.complete(OutboundMessage("test", "chat", "accepted"), publish_completion=False)
    await delivery.complete(OutboundMessage("test", "chat", "duplicate"), publish_completion=False)

    assert _visible_content([await bus.consume_outbound()]) == ["accepted"]
    assert bus.outbound_size == 0
