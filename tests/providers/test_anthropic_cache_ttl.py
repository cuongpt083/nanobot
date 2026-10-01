from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.base import LLMResponse, ProviderCallContext


def _anthropic_tools(*names: str) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": f"{name} tool",
            "input_schema": {"type": "object", "properties": {}},
        }
        for name in names
    ]


def test_apply_cache_control_default_marker_has_no_ttl() -> None:
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]
    system, new_msgs, marked_tools = AnthropicProvider._apply_cache_control(
        "system prompt",
        messages,
        _anthropic_tools("read_file", "write_file"),
    )
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}

    assert isinstance(new_msgs[-2]["content"], list)
    assert new_msgs[-2]["content"][0]["cache_control"] == {"type": "ephemeral"}

    assert marked_tools is not None
    assert marked_tools[-1]["cache_control"] == {"type": "ephemeral"}


def test_apply_cache_control_with_1h_retention() -> None:
    messages = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]
    system, new_msgs, marked_tools = AnthropicProvider._apply_cache_control(
        "system prompt",
        messages,
        _anthropic_tools("read_file", "write_file"),
        cache_ttl="1h",
    )
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    assert isinstance(new_msgs[-2]["content"], list)
    assert new_msgs[-2]["content"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    assert marked_tools is not None
    assert marked_tools[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


def test_build_kwargs_includes_ttl_when_passed() -> None:
    provider = AnthropicProvider(api_key="test-key", default_model="claude-sonnet-4-6")
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "u2"},
    ]
    kwargs = provider._build_kwargs(
        messages=messages,
        tools=_anthropic_tools("tool_a"),
        model="claude-sonnet-4-6",
        max_tokens=1000,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
        cache_ttl="1h",
    )
    system = kwargs.get("system")
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


@pytest.mark.asyncio
async def test_chat_with_context_passes_cache_ttl() -> None:
    provider = AnthropicProvider(api_key="test-key")
    dummy_response = LLMResponse(content="ok")

    with patch.object(provider, "chat", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = dummy_response

        # Long retention -> cache_ttl="1h"
        ctx_long = ProviderCallContext(cache_retention="long")
        await provider.chat_with_context(
            provider_context=ctx_long,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert mock_chat.call_args.kwargs.get("cache_ttl") == "1h"

        # Short retention -> cache_ttl=None
        ctx_short = ProviderCallContext(cache_retention="short")
        await provider.chat_with_context(
            provider_context=ctx_short,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert mock_chat.call_args.kwargs.get("cache_ttl") is None

        # None retention -> cache_ttl=None
        ctx_none = ProviderCallContext()
        await provider.chat_with_context(
            provider_context=ctx_none,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert mock_chat.call_args.kwargs.get("cache_ttl") is None


@pytest.mark.asyncio
async def test_chat_stream_with_context_passes_cache_ttl() -> None:
    provider = AnthropicProvider(api_key="test-key")
    dummy_response = LLMResponse(content="stream ok")

    with patch.object(provider, "chat_stream", new_callable=AsyncMock) as mock_stream:
        mock_stream.return_value = dummy_response

        ctx_long = ProviderCallContext(cache_retention="long")
        await provider.chat_stream_with_context(
            provider_context=ctx_long,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert mock_stream.call_args.kwargs.get("cache_ttl") == "1h"

        ctx_short = ProviderCallContext(cache_retention="short")
        await provider.chat_stream_with_context(
            provider_context=ctx_short,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert mock_stream.call_args.kwargs.get("cache_ttl") is None
