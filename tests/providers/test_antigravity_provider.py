"""Tests for the Antigravity provider (conversion, wrapper, SSE parsing)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

import nanobot.providers.antigravity_provider as provider_module
from nanobot.providers.antigravity_adapter import AntigravityAdapter
from nanobot.providers.antigravity_oauth import AntigravityToken
from nanobot.providers.antigravity_provider import (
    AntigravityProvider,
    _is_gemini3,
    _thinking_config,
)


def _provider(**kwargs: Any) -> AntigravityProvider:
    return AntigravityProvider(adapter=AntigravityAdapter(**kwargs))


def test_strip_prefix() -> None:
    provider = _provider()
    assert provider._strip_prefix("google-antigravity/gemini-3-pro-low") == "gemini-3-pro-low"
    assert provider._strip_prefix("google_antigravity/gemini-3-pro-low") == "gemini-3-pro-low"
    assert provider._strip_prefix("gemini-3-pro-low") == "gemini-3-pro-low"
    assert provider._strip_prefix("openai/gpt-4") == "openai/gpt-4"


def test_thinking_config() -> None:
    assert _thinking_config("gemini-3-pro-low", "high") == {
        "includeThoughts": True,
        "thinkingLevel": "HIGH",
    }
    assert _thinking_config("gemini-3-flash", "low") == {
        "includeThoughts": True,
        "thinkingLevel": "LOW",
    }
    # Disabled defaults for Gemini 3 use the lowest level (cannot fully disable).
    assert _thinking_config("gemini-3-pro-low", None) == {"thinkingLevel": "LOW"}
    assert _thinking_config("gemini-3-flash", None) == {"thinkingLevel": "MINIMAL"}
    assert _thinking_config("gemini-2.5-pro", None) == {"thinkingBudget": 0}
    assert _is_gemini3("gemini-3.1-pro-low")


def test_convert_messages_roles_and_tool_results() -> None:
    provider = _provider()
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "calling",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "do", "arguments": '{"x": 1}'}}
            ],
        },
        {"role": "tool", "content": "ok", "name": "do", "tool_call_id": "call_1"},
    ]
    contents = provider._convert_messages(messages, "gemini-3-pro-low")
    assert contents[0] == {"role": "user", "parts": [{"text": "hi"}]}
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0] == {"text": "calling"}
    assert contents[1]["parts"][1]["functionCall"]["name"] == "do"
    assert contents[1]["parts"][1]["functionCall"]["args"] == {"x": 1}
    # gemini-3 function calls carry the skip-signature sentinel.
    assert contents[1]["parts"][1]["thoughtSignature"] == "skip_thought_signature_validator"
    assert contents[2]["role"] == "user"
    assert contents[2]["parts"][0]["functionResponse"]["name"] == "do"
    assert contents[2]["parts"][0]["functionResponse"]["response"] == {"output": "ok"}


def test_convert_messages_adds_sentinel_for_gemini_3x_tiers() -> None:
    provider = _provider()
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": "do", "arguments": "{}"}}],
        }
    ]
    for model in (
        "gemini-3.6-flash-medium",
        "gemini-3.7-flash-tiered",
        "gemini-3.8-flash-tiered",
    ):
        part = provider._convert_messages(messages, model)[0]["parts"][0]
        assert part["functionCall"]["name"] == "do"
        assert part["thoughtSignature"] == "skip_thought_signature_validator"


def test_convert_messages_no_sentinel_for_claude() -> None:
    provider = _provider()
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "function": {"name": "do", "arguments": "{}"}}],
        }
    ]
    part = provider._convert_messages(messages, "claude-opus-4-6-thinking")[0]["parts"][0]
    assert "thoughtSignature" not in part


def test_convert_tools_switches_schema_field_for_claude() -> None:
    provider = _provider()
    tools = [
        {"type": "function", "function": {"name": "t", "parameters": {"type": "object"}}}
    ]
    gem = provider._convert_tools(tools, "gemini-3-pro-low")
    assert "parametersJsonSchema" in gem[0]["functionDeclarations"][0]
    claude = provider._convert_tools(tools, "claude-opus-4-6-thinking")
    assert "parameters" in claude[0]["functionDeclarations"][0]


def test_extract_usage_never_exceeds_logical_input() -> None:
    # cachedContentTokenCount > half of promptTokenCount used to trip
    # LLMUsage's "cache token counts cannot exceed logical input_tokens".
    usage = AntigravityProvider._extract_usage(
        {
            "usageMetadata": {
                "promptTokenCount": 100,
                "cachedContentTokenCount": 60,
                "candidatesTokenCount": 5,
                "totalTokenCount": 105,
            }
        },
        None,
    )
    assert usage is not None
    assert usage.input_tokens == 100
    assert usage.cache_read_tokens == 60
    assert usage.output_tokens == 5


def test_build_wrapper_injects_prelude_and_project() -> None:
    provider = _provider()
    wrapper = provider._build_wrapper(
        [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}],
        None,
        "google-antigravity/gemini-3-pro",
        max_tokens=100,
        temperature=0.2,
        reasoning_effort="high",
        tool_choice=None,
        project_id="proj-1",
    )
    assert wrapper["project"] == "proj-1"
    assert wrapper["model"] == "gemini-3-pro-low"  # normalized
    assert wrapper["requestType"] == "agent"
    assert wrapper["userAgent"] == "antigravity"
    parts = wrapper["request"]["systemInstruction"]["parts"]
    assert "You are Antigravity" in parts[0]["text"]
    assert parts[-1]["text"] == "be nice"
    assert wrapper["request"]["generationConfig"]["maxOutputTokens"] == 100


def _sse(*frames: dict[str, Any]) -> bytes:
    return ("".join(f"data: {json.dumps(frame)}\n\n" for frame in frames)).encode()


def _token() -> AntigravityToken:
    import time

    return AntigravityToken(
        access="tok", refresh="r", expires=int(time.time() * 1000) + 3_600_000, project_id="proj"
    )


async def test_chat_stream_parses_text_thinking_tools_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=_sse(
                {"response": {"candidates": [{"content": {"parts": [{"text": "Hel"}]}}]}},
                {"response": {"candidates": [{"content": {"parts": [{"text": "lo"}]}}]}},
                {
                    "response": {
                        "candidates": [
                            {"content": {"parts": [{"text": "think", "thought": True}]}}
                        ]
                    }
                },
                {
                    "response": {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"functionCall": {"name": "do", "args": {"a": 1}}}
                                    ]
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 10,
                            "cachedContentTokenCount": 2,
                            "candidatesTokenCount": 5,
                            "thoughtsTokenCount": 3,
                            "totalTokenCount": 15,
                        },
                    }
                },
            ),
            headers={"content-type": "text/event-stream"},
        )

    monkeypatch.setattr(provider_module, "get_antigravity_oauth_token", lambda **k: _token())
    provider = _provider()
    provider._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    deltas: list[str] = []
    thinking: list[str] = []
    tools: list[dict[str, Any]] = []

    async def on_content(delta: str) -> None:
        deltas.append(delta)

    async def on_thinking(delta: str) -> None:
        thinking.append(delta)

    async def on_tool(delta: dict[str, Any]) -> None:
        tools.append(delta)

    response = await provider.chat_stream(
        [{"role": "user", "content": "hi"}],
        on_content_delta=on_content,
        on_thinking_delta=on_thinking,
        on_tool_call_delta=on_tool,
    )

    assert response.content == "Hello"
    assert response.reasoning_content == "think"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].name == "do"
    assert response.tool_calls[0].arguments == {"a": 1}
    assert deltas == ["Hel", "lo"]
    assert thinking == ["think"]
    assert tools and tools[0]["name"] == "do"
    assert response.usage is not None
    # input_tokens is the logical total (promptTokenCount), which includes cache.
    assert response.usage.input_tokens == 10
    assert response.usage.cache_read_tokens == 2
    assert response.usage.output_tokens == 8
    # Wire assertions
    assert captured["url"].endswith("/v1internal:streamGenerateContent?alt=sse")
    assert captured["json"]["project"] == "proj"
    assert captured["headers"]["user-agent"].startswith("antigravity/")


def test_convert_messages_repairs_turn_order() -> None:
    provider = _provider()
    contents = provider._normalize_turn_order(provider._convert_messages(
        [
            {"role": "assistant", "content": "orphan", "tool_calls": [
                {"id": "c0", "function": {"name": "a", "arguments": "{}"}}
            ]},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "again"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "function": {"name": "a", "arguments": "{}"}}
            ]},
            {"role": "tool", "tool_call_id": "c1", "name": "a", "content": "ok"},
        ],
        "gemini-3-flash",
    ))
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert [p["text"] for p in contents[0]["parts"]] == ["hi", "again"]


async def test_empty_stream_with_error_finish_reason_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse({"response": {"candidates": [{"finishReason": "SAFETY"}]}}),
            headers={"content-type": "text/event-stream"},
        )

    monkeypatch.setattr(provider_module, "get_antigravity_oauth_token", lambda **k: _token())
    provider = _provider()
    provider._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    response = await provider.chat_stream([{"role": "user", "content": "hi"}])
    assert response.finish_reason == "error"
    assert response.error_kind == "empty_response"
    assert "SAFETY" in (response.content or "")
    assert response.error_should_retry is False


async def test_chat_returns_oauth_error_without_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nanobot.providers.antigravity_oauth import AntigravityOAuthReauthRequiredError

    def _fail(**_kwargs: object) -> AntigravityToken:
        raise AntigravityOAuthReauthRequiredError("not signed in")

    monkeypatch.setattr(provider_module, "get_antigravity_oauth_token", _fail)
    response = await _provider().chat([{"role": "user", "content": "hi"}])
    assert response.finish_reason == "error"
    assert response.error_kind == "oauth_auth_required"
    assert response.error_should_retry is False


async def test_endpoint_fallback_on_403(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "daily-cloudcode-pa" in str(request.url):
            return httpx.Response(403, json={"error": {"message": "no"}})
        return httpx.Response(
            200,
            content=_sse(
                {"response": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}}
            ),
            headers={"content-type": "text/event-stream"},
        )

    monkeypatch.setattr(provider_module, "get_antigravity_oauth_token", lambda **k: _token())
    provider = _provider(
        endpoint="https://daily-cloudcode-pa.googleapis.com",
        endpoint_fallbacks=("https://cloudcode-pa.googleapis.com",),
    )
    provider._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    response = await provider.chat([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert len(calls) == 2
