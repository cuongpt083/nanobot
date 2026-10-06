from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse, LLMUsage, ProviderCallContext
from nanobot.providers.factory import make_provider
from nanobot.providers.oauth_model_catalog import OAuthModelCatalogSnapshot
from nanobot.providers.openai_responses import build_responses_state, responses_state_items
from nanobot.providers.registry import ProviderModelSpec, find_by_name
from nanobot.providers.xai_grok_provider import (
    DEFAULT_XAI_GROK_MODEL,
    XAIGrokProvider,
    _bounded_error_body,
    _build_headers,
    _build_reasoning_options,
    _build_xai_http_error,
    _prompt_cache_key,
    _request_xai,
    _xai_error_response,
    _XAIHTTPError,
    _XAIIncompleteHostedToolError,
)


def _token(access: str = "subscription-token") -> SimpleNamespace:
    return SimpleNamespace(
        access=access,
        refresh="refresh-token",
        expires=int(time.time() * 1000) + 3_600_000,
        account_id="account",
    )


def _mock_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider.get_xai_oauth_token",
        lambda **_kwargs: _token(),
    )


def _mock_model_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    *,
    supports_backend_search: bool,
) -> None:
    def fake_catalog(*_args, **_kwargs):
        return OAuthModelCatalogSnapshot(
            models=(
                ProviderModelSpec(
                    id="xai-grok/grok-4.5",
                    label="Grok 4.5",
                    supports_backend_search=supports_backend_search,
                ),
                ProviderModelSpec(
                    id="xai-grok/grok-4.6",
                    label="Grok 4.6",
                    supports_backend_search=supports_backend_search,
                ),
            ),
            source="remote",
            fetched_at=1,
        )

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider.get_xai_grok_model_catalog",
        fake_catalog,
    )


def test_xai_grok_registry_exposes_curated_x_search_models() -> None:
    spec = find_by_name("xai_grok")

    assert spec is not None
    assert spec.is_oauth is True
    assert spec.backend == "xai_grok"
    assert spec.builtin_models[0].id == DEFAULT_XAI_GROK_MODEL
    assert [model.id for model in spec.builtin_models] == [
        "xai-grok/grok-4.6",
        "xai-grok/grok-4.5",
    ]
    assert spec.builtin_models[0].context_window == 500000
    assert "when supported" in spec.builtin_models[0].description


def test_reasoning_options_omit_disabled_effort() -> None:
    assert _build_reasoning_options("none") == {"summary": "concise"}


@pytest.mark.asyncio
async def test_provider_retries_stream_eof_before_returning_content(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    calls = 0

    async def fake_request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("stream ended early")
        return LLMResponse(content="complete answer", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()
    provider._CHAT_RETRY_DELAYS = (0,)

    response = await provider.chat_stream_with_retry([{"role": "user", "content": "hello"}])

    assert response.content == "complete answer"
    assert response.finish_reason == "stop"
    assert calls == 2


@pytest.mark.asyncio
async def test_provider_injects_hosted_x_search_and_required_proxy_headers(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=True)
    calls: list[tuple[str, dict[str, str], dict[str, Any]]] = []

    async def fake_request(url, headers, body, **_kwargs):
        calls.append((url, headers, body))
        return LLMResponse(
            content="answer [[1]](https://x.com/example/status/1)",
            finish_reason="stop",
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object"},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "x_search",
                "description": "A colliding local tool",
                "parameters": {"type": "object"},
            },
        },
    ]

    response = await provider.chat(
        [{"role": "user", "content": "What is happening on X?"}],
        tools=tools,
        max_tokens=1234,
        temperature=0.2,
        reasoning_effort="high",
    )

    assert response.content == "answer [[1]](https://x.com/example/status/1)"
    url, headers, body = calls[0]
    assert url == "https://cli-chat-proxy.grok.com/v1/responses"
    assert body["model"] == "grok-4.6"
    assert body["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object"},
            "strict": False,
        },
        {"type": "x_search"},
    ]
    assert body["max_output_tokens"] == 1234
    assert body["temperature"] == 0.2
    assert body["stream_tool_calls"] is True
    assert body["reasoning"] == {"summary": "concise", "effort": "high"}
    assert body["store"] is False
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["max_turns"] == 5
    assert headers["Authorization"] == "Bearer subscription-token"
    assert headers["X-XAI-Token-Auth"] == "xai-grok-cli"
    assert headers["x-authenticateresponse"] == "authenticate-response"
    assert headers["x-grok-client-identifier"] == "nanobot"
    assert headers["x-grok-client-mode"] == "headless"
    assert headers["x-grok-model-override"] == "grok-4.6"


@pytest.mark.asyncio
async def test_explicit_parameterized_x_search_is_preserved_without_catalog_lookup(
    monkeypatch,
) -> None:
    _mock_token(monkeypatch)
    bodies: list[dict[str, Any]] = []

    def unexpected_catalog_lookup(*_args, **_kwargs):
        raise AssertionError("explicit raw tools must not depend on model catalog metadata")

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider.get_xai_grok_model_catalog",
        unexpected_catalog_lookup,
    )
    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    hosted_tool = {
        "type": "x_search",
        "allowed_x_handles": ["nanobot_ai"],
        "from_date": "2026-01-01",
    }
    provider = XAIGrokProvider(
        extra_body={
            "parallel_tool_calls": False,
            "tools": [hosted_tool, {"type": "code_interpreter", "container": "auto"}],
        }
    )

    response = await provider.chat(
        [{"role": "user", "content": "search"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object"},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "x_search",
                    "description": "A colliding local tool",
                    "parameters": {"type": "object"},
                },
            },
        ],
    )

    assert response.content == "ok"
    assert bodies[0]["parallel_tool_calls"] is False
    assert bodies[0]["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object"},
            "strict": False,
        },
        hosted_tool,
        {"type": "code_interpreter", "container": "auto"},
    ]


@pytest.mark.asyncio
async def test_explicit_empty_tools_disables_catalog_lookup_and_hosted_tool(monkeypatch) -> None:
    _mock_token(monkeypatch)
    bodies: list[dict[str, Any]] = []

    def unexpected_catalog_lookup(*_args, **_kwargs):
        raise AssertionError("explicitly disabled X Search must not fetch model capabilities")

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider.get_xai_grok_model_catalog",
        unexpected_catalog_lookup,
    )
    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider(extra_body={"tools": []})

    response = await provider.chat(
        [{"role": "user", "content": "hello"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )

    assert response.content == "ok"
    assert bodies[0]["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object"},
            "strict": False,
        }
    ]
    assert "max_turns" not in bodies[0]


@pytest.mark.asyncio
async def test_provider_keeps_local_x_search_when_model_does_not_support_hosted_search(
    monkeypatch,
) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    bodies: list[dict[str, Any]] = []

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "x_search",
                "description": "A local search fallback",
                "parameters": {"type": "object"},
            },
        }
    ]

    response = await provider.chat([{"role": "user", "content": "search"}], tools=tools)

    assert response.content == "ok"
    assert bodies[0]["tools"] == [
        {
            "type": "function",
            "name": "x_search",
            "description": "A local search fallback",
            "parameters": {"type": "object"},
            "strict": False,
        }
    ]
    assert "max_turns" not in bodies[0]
    assert bodies[0]["instructions"] == ""


@pytest.mark.asyncio
async def test_provider_refreshes_and_retries_exactly_once_after_401(monkeypatch) -> None:
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    token_calls: list[tuple[str | None, bool]] = []

    def fake_token(*, proxy=None, force_refresh=False):
        token_calls.append((proxy, force_refresh))
        return _token("fresh-token" if force_refresh else "stale-token")

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider.get_xai_oauth_token",
        fake_token,
    )
    request_tokens: list[str] = []

    async def fake_request(_url, headers, _body, **_kwargs):
        request_tokens.append(headers["Authorization"])
        if len(request_tokens) == 1:
            raise _XAIHTTPError("unauthorized", status_code=401, should_retry=False)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider(proxy="http://127.0.0.1:7890")

    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert token_calls == [
        ("http://127.0.0.1:7890", False),
        ("http://127.0.0.1:7890", True),
    ]
    assert request_tokens == ["Bearer stale-token", "Bearer fresh-token"]


@pytest.mark.asyncio
async def test_second_401_is_non_retryable_and_prompts_reauthentication(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)

    async def always_unauthorized(*_args, **_kwargs):
        raise _XAIHTTPError(
            "xAI rejected the login. Sign in again with `nanobot provider login xai-grok`.",
            status_code=401,
            should_retry=False,
        )

    monkeypatch.setattr(
        "nanobot.providers.xai_grok_provider._request_xai",
        always_unauthorized,
    )
    provider = XAIGrokProvider()

    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.finish_reason == "error"
    assert response.error_status_code == 401
    assert response.error_kind == "http"
    assert response.error_should_retry is False
    assert "nanobot provider login xai-grok" in (response.content or "")


@pytest.mark.asyncio
async def test_factory_builds_xai_provider_and_applies_explicit_body_overrides(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=True)
    bodies: list[dict[str, Any]] = []

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "model": "xai-grok/grok-4.5",
                    "provider": "xai_grok",
                }
            },
            "providers": {
                "xaiGrok": {
                    "proxy": "http://127.0.0.1:7890",
                    "extraBody": {
                        "parallel_tool_calls": False,
                        "max_turns": 2,
                    },
                }
            },
        }
    )

    provider = make_provider(config)
    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert isinstance(provider, XAIGrokProvider)
    assert provider.proxy == "http://127.0.0.1:7890"
    assert response.content == "ok"
    assert bodies[0]["parallel_tool_calls"] is False
    assert bodies[0]["max_turns"] == 2
    assert {"type": "x_search"} in bodies[0]["tools"]


@pytest.mark.asyncio
async def test_raw_response_request_streams_text_usage_and_inline_citations(monkeypatch) -> None:
    original_client = httpx.AsyncClient
    captured: dict[str, Any] = {}
    events = [
        {"type": "response.output_text.delta", "delta": "Live result "},
        {
            "type": "response.output_text.delta",
            "delta": "[[1]](https://x.com/example/status/1)",
        },
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "usage": {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
            },
        },
    ]
    content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, content=content, request=request)

    def fake_client(**kwargs) -> httpx.AsyncClient:
        captured["kwargs"] = kwargs
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)
    deltas: list[str] = []

    result = await _request_xai(
        "https://cli-chat-proxy.grok.com/v1/responses",
        _build_headers("secret", "grok-4.5"),
        {"model": "grok-4.5", "tools": [{"type": "x_search"}]},
        on_content_delta=lambda delta: _append(deltas, delta),
    )

    assert result.content == "Live result [[1]](https://x.com/example/status/1)"
    assert result.finish_reason == "stop"
    assert result.usage == LLMUsage.reported(input_tokens=8, output_tokens=4)
    assert deltas == ["Live result ", "[[1]](https://x.com/example/status/1)"]
    assert captured["json"]["tools"] == [{"type": "x_search"}]


@pytest.mark.asyncio
async def test_raw_response_request_streams_hosted_x_search_lifecycle(monkeypatch) -> None:
    original_client = httpx.AsyncClient
    events = [
        {
            "type": "response.custom_tool_call_input.done",
            "item_id": "x-search-1",
            "input": '{"query":"nanobot oauth"}',
        },
        {
            "type": "response.output_item.done",
            "item": {
                "type": "custom_tool_call",
                "id": "x-search-1",
                "name": "x_semantic_search",
                "input": '{"query":"nanobot oauth"}',
                "output": [{"text": "large hosted result must not enter activity events"}],
            },
        },
        {
            "type": "response.completed",
            "response": {"status": "completed", "usage": {}},
        },
    ]
    content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    def fake_client(**kwargs) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)
    tool_events: list[dict[str, Any]] = []

    result = await _request_xai(
        "https://cli-chat-proxy.grok.com/v1/responses",
        _build_headers("secret", "grok-4.5"),
        {"model": "grok-4.5", "tools": [{"type": "x_search"}]},
        on_tool_call_delta=lambda event: _append(tool_events, event),
    )

    assert result.content == ""
    assert tool_events == [
        {
            "kind": "hosted_tool",
            "phase": "start",
            "call_id": "x-search-1",
            "name": "x_search",
            "arguments": {"query": "nanobot oauth"},
            "result": None,
        },
        {
            "kind": "hosted_tool",
            "phase": "end",
            "call_id": "x-search-1",
            "name": "x_search",
            "arguments": {"query": "nanobot oauth"},
            "result": {"name": "x_semantic_search"},
        },
    ]
    assert "large hosted result" not in json.dumps(tool_events)


@pytest.mark.asyncio
async def test_raw_response_request_streams_official_x_search_lifecycle(monkeypatch) -> None:
    original_client = httpx.AsyncClient
    events = [
        {
            "type": "response.output_item.added",
            "item": {
                "type": "x_search_call",
                "id": "x-search-1",
                "status": "in_progress",
                "action": {"query": "nanobot oauth"},
            },
        },
        {
            "type": "response.output_item.done",
            "item": {
                "type": "x_search_call",
                "id": "x-search-1",
                "status": "completed",
                "action": {"query": "nanobot oauth"},
            },
        },
        {
            "type": "response.completed",
            "response": {"status": "completed", "usage": {}},
        },
    ]
    content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    def fake_client(**kwargs) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)
    tool_events: list[dict[str, Any]] = []

    await _request_xai(
        "https://cli-chat-proxy.grok.com/v1/responses",
        _build_headers("secret", "grok-4.6"),
        {"model": "grok-4.6", "tools": [{"type": "x_search"}]},
        on_tool_call_delta=lambda event: _append(tool_events, event),
    )

    assert [(event["phase"], event["name"]) for event in tool_events] == [
        ("start", "x_search"),
        ("end", "x_search"),
    ]
    assert tool_events[-1]["result"] == {"status": "completed"}


@pytest.mark.asyncio
async def test_raw_response_rejects_unfinished_hosted_tool_and_closes_progress(
    monkeypatch,
) -> None:
    original_client = httpx.AsyncClient
    events = [
        {
            "type": "response.custom_tool_call_input.done",
            "item_id": "x-search-1",
            "input": '{"query":"nanobot oauth"}',
        },
        {"type": "response.output_text.delta", "delta": "I will keep searching."},
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "usage": {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
            },
        },
    ]
    content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    def fake_client(**kwargs) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)
    tool_events: list[dict[str, Any]] = []

    with pytest.raises(_XAIIncompleteHostedToolError) as caught:
        await _request_xai(
            "https://cli-chat-proxy.grok.com/v1/responses",
            _build_headers("secret", "grok-4.6"),
            {"model": "grok-4.6", "tools": [{"type": "x_search"}]},
            on_tool_call_delta=lambda event: _append(tool_events, event),
        )

    assert caught.value.usage == LLMUsage.reported(input_tokens=8, output_tokens=4)
    assert [event["phase"] for event in tool_events] == ["start", "error"]
    assert "before this hosted tool completed" in tool_events[-1]["error"]


@pytest.mark.asyncio
async def test_provider_recovers_unfinished_hosted_tool_once_and_preserves_usage(
    monkeypatch,
) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=True)
    attempts = 0
    request_ids: list[str] = []
    conv_ids: list[str] = []
    streamed: list[str] = []
    recovered: list[bool] = []
    first_usage = LLMUsage.reported(input_tokens=10, output_tokens=2)
    second_usage = LLMUsage.reported(input_tokens=11, output_tokens=4)

    async def fake_request(_url, headers, body, **kwargs):
        nonlocal attempts
        attempts += 1
        request_ids.append(headers["x-grok-req-id"])
        conv_ids.append(headers["x-grok-conv-id"])
        assert body["max_turns"] == 5
        if attempts == 1:
            await kwargs["on_content_delta"]("I will keep searching.")
            raise _XAIIncompleteHostedToolError(
                [{"name": "x_search", "call_id": "search-1"}],
                usage=first_usage,
            )
        await kwargs["on_content_delta"]("Final researched answer.")
        return LLMResponse(content="Final researched answer.", finish_reason="stop", usage=second_usage)

    async def on_recover() -> None:
        recovered.append(True)

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()

    response = await provider.chat_stream_with_retry(
        [{"role": "user", "content": "Search X"}],
        on_content_delta=lambda delta: _append(streamed, delta),
        on_stream_recover=on_recover,
    )

    assert attempts == 2
    assert len(set(request_ids)) == 2
    assert conv_ids[0] == conv_ids[1]
    assert recovered == [True]
    assert streamed == ["I will keep searching.", "Final researched answer."]
    assert response.content == "Final researched answer."
    assert response.usage == first_usage + second_usage


@pytest.mark.asyncio
async def test_provider_preserves_usage_when_hosted_tool_recovery_also_fails(
    monkeypatch,
) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=True)
    attempts = 0
    usage = LLMUsage.reported(input_tokens=10, output_tokens=2)

    async def fake_request(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise _XAIIncompleteHostedToolError(
            [{"name": "x_search", "call_id": f"search-{attempts}"}],
            usage=usage,
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()

    response = await provider.chat_stream_with_retry(
        [{"role": "user", "content": "Search X"}],
        on_stream_recover=lambda: _append([], True),
    )

    assert attempts == 2
    assert response.finish_reason == "error"
    assert response.usage == usage + usage


@pytest.mark.asyncio
async def test_raw_response_error_preserves_bounded_redacted_body(monkeypatch) -> None:
    original_client = httpx.AsyncClient
    raw = json.dumps(
        {
            "code": "invalid-argument",
            "message": "Hosted x_search is not supported by grok-4.5",
            "access_token": "must-not-leak",
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=raw, request=request)

    def fake_client(**kwargs) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)

    with pytest.raises(_XAIHTTPError) as caught:
        await _request_xai(
            "https://cli-chat-proxy.grok.com/v1/responses",
            _build_headers("secret", "grok-4.5"),
            {"model": "grok-4.5"},
        )

    error = caught.value
    assert error.status_code == 400
    assert error.error_code == "invalid-argument"
    assert error.should_retry is False
    assert error.response_body == (
        '{"code":"invalid-argument","message":"Hosted x_search is not supported by '
        'grok-4.5","access_token":"[REDACTED]"}'
    )
    assert f"Response body: {error.response_body}" in str(error)
    assert "must-not-leak" not in str(error)

    provider_response = _xai_error_response(error)
    assert provider_response.error_status_code == 400
    assert provider_response.error_code == "invalid-argument"
    assert error.response_body in (provider_response.content or "")


def test_plain_error_body_is_single_line_and_bounded() -> None:
    detail = _bounded_error_body("Bearer secret-token\n" + "x" * 1100)

    assert detail is not None
    assert detail.startswith("Bearer [REDACTED] ")
    assert detail.endswith("…")
    assert len(detail) == 1001


def test_client_version_rejection_explains_update_and_preserves_body() -> None:
    raw = json.dumps(
        {
            "code": "upgrade-required",
            "message": "Client version 0.2.109 is no longer supported",
        }
    )

    error = _build_xai_http_error(426, httpx.Headers(), raw)
    response = _xai_error_response(error)

    assert error.status_code == 426
    assert error.should_retry is False
    assert error.response_body == (
        '{"code":"upgrade-required","message":"Client version 0.2.109 is no longer supported"}'
    )
    assert "xAI requires a newer Grok client version. Update nanobot and try again." in str(error)
    assert error.response_body in str(error)
    assert response.error_status_code == 426
    assert error.response_body in (response.content or "")


def test_large_json_error_body_redacts_camel_case_credentials_before_bounding() -> None:
    detail = _bounded_error_body(
        json.dumps(
            {
                "accessToken": "access-must-not-leak",
                "refresh-token": "refresh-must-not-leak",
                "padding": "x" * 33_000,
            }
        )
    )

    assert detail is not None
    assert '"accessToken":"[REDACTED]"' in detail
    assert '"refresh-token":"[REDACTED]"' in detail
    assert "access-must-not-leak" not in detail
    assert "refresh-must-not-leak" not in detail
    assert detail.endswith("…")
    assert len(detail) == 1001


async def _append(target: list[Any], value: Any) -> None:
    target.append(value)


def test_build_headers_advertises_a_supported_grok_client_version() -> None:
    from nanobot.providers.xai_oauth import XAI_CLIENT_VERSION

    headers = _build_headers("secret", "grok-4.6")
    assert headers["x-grok-client-version"] == XAI_CLIENT_VERSION
    # xAI's CLI chat proxy returns HTTP 426 below this floor.
    assert tuple(int(part) for part in XAI_CLIENT_VERSION.split(".")) >= (1, 0, 13)


@pytest.mark.asyncio
async def test_prompt_cache_key_prefers_stable_session_id(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    bodies: list[dict[str, Any]] = []
    headers_seen: list[dict[str, str]] = []

    async def fake_request(_url, headers, body, **_kwargs):
        bodies.append(body)
        headers_seen.append(headers)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()

    for session_id, content in (
        ("session-a", "first request"),
        ("session-a", "different visible prefix"),
        ("session-b", "first request"),
    ):
        await provider.chat_with_context(
            provider_context=ProviderCallContext(session_id=session_id),
            messages=[{"role": "user", "content": content}],
        )

    key_a = _prompt_cache_key("session-a")
    key_b = _prompt_cache_key("session-b")
    assert bodies[0]["prompt_cache_key"] == bodies[1]["prompt_cache_key"] == key_a
    assert bodies[2]["prompt_cache_key"] == key_b
    assert key_a != key_b
    for headers, expected in zip(headers_seen, (key_a, key_a, key_b), strict=True):
        assert headers["x-grok-conv-id"] == expected
        assert headers["x-grok-session-id"] == expected
        assert headers["x-grok-agent-id"] == expected
    assert len({headers["x-grok-req-id"] for headers in headers_seen}) == 3


@pytest.mark.asyncio
async def test_omits_prompt_cache_key_without_session_id(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    bodies: list[dict[str, Any]] = []
    headers_seen: list[dict[str, str]] = []

    async def fake_request(_url, headers, body, **_kwargs):
        bodies.append(body)
        headers_seen.append(headers)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()

    await provider.chat([{"role": "user", "content": "first"}])
    await provider.chat([{"role": "user", "content": "second"}])

    assert "prompt_cache_key" not in bodies[0]
    assert "prompt_cache_key" not in bodies[1]
    assert headers_seen[0]["x-grok-conv-id"] == headers_seen[1]["x-grok-conv-id"]
    assert headers_seen[0]["x-grok-session-id"] == headers_seen[0]["x-grok-conv-id"]
    assert headers_seen[0]["x-grok-agent-id"] == headers_seen[0]["x-grok-conv-id"]
    assert headers_seen[0]["x-grok-req-id"] != headers_seen[1]["x-grok-req-id"]


@pytest.mark.asyncio
async def test_chat_stream_with_retry_uses_sticky_session_headers(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    headers_seen: list[dict[str, str]] = []

    async def fake_request(_url, headers, body, **_kwargs):
        headers_seen.append(headers)
        assert body["prompt_cache_key"] == _prompt_cache_key("stream-session")
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider()

    response = await provider.chat_stream_with_retry(
        [{"role": "user", "content": "hello"}],
        provider_context=ProviderCallContext(session_id="stream-session"),
    )

    assert response.content == "ok"
    expected = _prompt_cache_key("stream-session")
    assert headers_seen[0]["x-grok-conv-id"] == expected
    assert headers_seen[0]["x-grok-session-id"] == expected
    assert headers_seen[0]["x-grok-agent-id"] == expected


@pytest.mark.asyncio
async def test_extra_body_prompt_cache_key_overrides_session_hash(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    bodies: list[dict[str, Any]] = []
    headers_seen: list[dict[str, str]] = []

    async def fake_request(_url, headers, body, **_kwargs):
        bodies.append(body)
        headers_seen.append(headers)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)
    provider = XAIGrokProvider(extra_body={"prompt_cache_key": "explicit-cache-key"})

    await provider.chat_with_context(
        provider_context=ProviderCallContext(session_id="session-a"),
        messages=[{"role": "user", "content": "hello"}],
    )

    assert bodies[0]["prompt_cache_key"] == "explicit-cache-key"
    assert headers_seen[0]["x-grok-conv-id"] == "explicit-cache-key"
    assert headers_seen[0]["x-grok-session-id"] == "explicit-cache-key"


@pytest.mark.asyncio
async def test_replays_encrypted_reasoning_and_strips_item_ids(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    provider = XAIGrokProvider()
    state = build_responses_state(
        provider=provider._responses_state_provider(),
        model="grok-4.6",
        input_items=[{
            "id": "msg_user",
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Check the weather"}],
        }],
        output_items=[
            {
                "id": "rs_reasoning",
                "type": "reasoning",
                "encrypted_content": "opaque reasoning",
                "status": "completed",
                "summary": [],
            },
            {
                "id": "fc_read",
                "type": "function_call",
                "call_id": "call_read",
                "name": "read_file",
                "arguments": '{"path":"weather/SKILL.md"}',
                "status": "completed",
            },
        ],
    )
    bodies: list[dict[str, Any]] = []

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return LLMResponse(content="done", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)

    response = await provider.chat(
        [{"role": "user", "content": "Check the weather"}],
        provider_context=ProviderCallContext(
            conversation_state=state.with_pending_messages([{
                "role": "tool",
                "tool_call_id": "call_read|fc_read",
                "content": "weather skill contents",
            }]),
        ),
    )

    assert response.content == "done"
    input_items = bodies[0]["input"]
    assert [item.get("type") for item in input_items] == [
        "message",
        "reasoning",
        "function_call",
        "function_call_output",
    ]
    assert all("id" not in item for item in input_items)
    assert "status" not in input_items[1]
    assert input_items[1]["encrypted_content"] == "opaque reasoning"
    assert input_items[2]["call_id"] == "call_read"
    assert input_items[3]["call_id"] == "call_read"
    assert provider.can_resume_conversation_state(state, "xai-grok/grok-4.6") is True
    assert provider.can_resume_conversation_state(state, "grok-4.5") is False


@pytest.mark.asyncio
async def test_replay_drops_hosted_search_output_items(monkeypatch) -> None:
    _mock_token(monkeypatch)
    _mock_model_capabilities(monkeypatch, supports_backend_search=False)
    provider = XAIGrokProvider()
    state = build_responses_state(
        provider=provider._responses_state_provider(),
        model="grok-4.6",
        input_items=[{
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "search X"}],
        }],
        output_items=[
            {
                "id": "x-search-1",
                "type": "x_search_call",
                "status": "completed",
                "action": {"query": "nanobot oauth"},
            },
            {
                "id": "custom-1",
                "type": "custom_tool_call",
                "name": "x_semantic_search",
                "input": '{"query":"nanobot oauth"}',
            },
            {
                "id": "rs_reasoning",
                "type": "reasoning",
                "encrypted_content": "opaque reasoning",
                "summary": [],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "found it"}],
            },
        ],
    )
    bodies: list[dict[str, Any]] = []

    async def fake_request(_url, _headers, body, **_kwargs):
        bodies.append(body)
        return LLMResponse(content="ok", finish_reason="stop")

    monkeypatch.setattr("nanobot.providers.xai_grok_provider._request_xai", fake_request)

    await provider.chat(
        [{"role": "user", "content": "search X"}],
        provider_context=ProviderCallContext(
            conversation_state=state.with_pending_messages([
                {"role": "user", "content": "follow up"},
            ]),
        ),
    )

    input_items = bodies[0]["input"]
    input_types = [item.get("type") for item in input_items]
    assert "x_search_call" not in input_types
    assert "custom_tool_call" not in input_types
    assert "reasoning" in input_types
    assert any(
        item.get("role") == "user" and "follow up" in str(item.get("content"))
        for item in input_items
    )


@pytest.mark.asyncio
async def test_raw_response_captures_encrypted_reasoning_state(monkeypatch) -> None:
    original_client = httpx.AsyncClient
    reasoning_item = {
        "id": "rs_1",
        "type": "reasoning",
        "encrypted_content": "opaque-secret",
        "summary": [],
    }
    events = [
        {"type": "response.output_item.done", "item": reasoning_item},
        {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": [reasoning_item],
                "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            },
        },
    ]
    content = "".join(f"data: {json.dumps(event)}\n\n" for event in events)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    def fake_client(**kwargs) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.MockTransport(handler),
            timeout=kwargs["timeout"],
        )

    monkeypatch.setattr("nanobot.providers.xai_grok_provider.httpx.AsyncClient", fake_client)

    result = await _request_xai(
        "https://cli-chat-proxy.grok.com/v1/responses",
        _build_headers("secret", "grok-4.6"),
        {
            "model": "grok-4.6",
            "input": [{
                "id": "msg_user",
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            }],
        },
    )

    assert result.finish_reason == "stop"
    assert result.provider_state is not None
    assert result.provider_state.provider == (
        "xai_grok:https://cli-chat-proxy.grok.com/v1/responses"
    )
    items = responses_state_items(result.provider_state)
    assert items is not None
    assert any(item.get("encrypted_content") == "opaque-secret" for item in items)
