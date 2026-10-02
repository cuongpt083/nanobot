"""End-to-end tests: proxy ⇄ fake upstream, streaming and non-streaming."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
from aiohttp import web

from nanobot.providers.patcher.proxy import AnthropicPatcherProxy
from nanobot.providers.patcher.rules import PatcherConfig, PatcherRule

_SEEN_KEY: web.AppKey[list[dict[str, Any]]] = web.AppKey("seen", list)


def _config(base_url: str) -> PatcherConfig:
    return PatcherConfig(
        enabled=True,
        target_base_url=base_url,
        claude_code_version="2.1.280",
        attribution_template="x-anthropic-billing-header: cc_version=${version}.a1b;",
        add_session_id=True,
        rules=[
            PatcherRule(
                id="sys-brand",
                category="system",
                find="OpenClaw",
                replace="Claude Code",
            ),
            PatcherRule(
                id="tool",
                category="tool_name",
                find="sessions_list",
                replace="Sessions_list",
            ),
            PatcherRule(
                id="resp",
                category="response",
                find="HEALTH_CHECK",
                replace="HEARTBEAT_OK",
            ),
            PatcherRule(
                id="ua",
                category="header",
                find="user-agent",
                replace="claude-cli/${version}",
            ),
        ],
    )


async def _upstream_handler(request: web.Request) -> web.StreamResponse:
    payload = await request.json()
    seen = request.app[_SEEN_KEY]
    seen.append(
        {
            "payload": payload,
            "headers": {k.lower(): v for k, v in request.headers.items()},
        }
    )

    if payload.get("stream"):
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)

        def event(name: str, data: dict[str, Any]) -> bytes:
            return f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()

        await response.write(
            event("message_start", {"type": "message_start", "message": {"content": []}})
        )
        await response.write(
            event(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "tool_use", "name": "Sessions_list"},
                },
            )
        )
        await response.write(
            event(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '{"q":"a"}'},
                },
            )
        )
        await response.write(
            event("content_block_stop", {"type": "content_block_stop", "index": 1})
        )
        await response.write(event("message_stop", {"type": "message_stop"}))
        await response.write_eof()
        return response

    return web.json_response(
        {
            "content": [
                {"type": "text", "text": "HEALTH_CHECK done"},
                {
                    "type": "tool_use",
                    "name": "Sessions_list",
                    "input": {"q": "a"},
                },
            ]
        }
    )


@asynccontextmanager
async def _start_upstream() -> AsyncIterator[tuple[str, list[dict[str, Any]]]]:
    app = web.Application()
    app[_SEEN_KEY] = []
    app.router.add_post("/v1/messages", _upstream_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    server = site._server
    port = server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        yield f"http://127.0.0.1:{port}", app[_SEEN_KEY]
    finally:
        await runner.cleanup()


async def test_proxy_non_streaming_reverses_and_rewrites_request() -> None:
    async with _start_upstream() as (base_url, seen):
        proxy = AnthropicPatcherProxy(_config(base_url))
        await proxy.start(0)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://127.0.0.1:{proxy.port}/v1/messages",
                    json={
                        "model": "claude-sonnet-4-6",
                        "stream": False,
                        "system": [{"type": "text", "text": "Hi OpenClaw"}],
                        "tools": [{"name": "sessions_list", "description": "d"}],
                    },
                    headers={
                        "authorization": "Bearer tok",
                        "anthropic-version": "2023-06-01",
                    },
                ) as response:
                    body = await response.json()
        finally:
            await proxy.stop()

    # Request side: attribution injected, branding + tool renamed.
    forwarded = seen[0]["payload"]
    assert forwarded["system"][0]["text"].startswith("x-anthropic-billing-header")
    assert forwarded["system"][1]["text"] == "Hi Claude Code"
    assert forwarded["tools"][0]["name"] == "Sessions_list"
    assert seen[0]["headers"]["user-agent"] == "claude-cli/2.1.280"
    assert seen[0]["headers"]["authorization"] == "Bearer tok"
    assert seen[0]["headers"]["x-claude-code-session-id"]

    # Response side: tool name + text reversed.
    assert body["content"][0]["text"] == "HEARTBEAT_OK done"
    assert body["content"][1]["name"] == "sessions_list"


async def test_proxy_streaming_emits_wellformed_frames() -> None:
    async with _start_upstream() as (base_url, _):
        proxy = AnthropicPatcherProxy(_config(base_url))
        await proxy.start(0)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://127.0.0.1:{proxy.port}/v1/messages",
                    json={"model": "m", "stream": True, "messages": []},
                    headers={"authorization": "Bearer tok"},
                ) as response:
                    text = await response.text()
        finally:
            await proxy.stop()

    frames = [frame for frame in text.split("\n\n") if frame]
    assert frames
    for frame in frames:
        assert frame.startswith("event: "), frame
    # The tool-input fragments were re-emitted whole, patched and preceded by an
    # event line so streaming clients never lose the tool call.
    assert '"name": "sessions_list"' in text
    assert '"type": "input_json_delta"' in text


async def test_proxy_health_endpoint() -> None:
    async with _start_upstream() as (base_url, _):
        proxy = AnthropicPatcherProxy(_config(base_url))
        await proxy.start(0)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{proxy.port}/health") as response:
                    body = await response.json()
            assert body["status"] == "ok"
        finally:
            await proxy.stop()


async def test_proxy_rejects_invalid_json() -> None:
    async with _start_upstream() as (base_url, _):
        proxy = AnthropicPatcherProxy(_config(base_url))
        await proxy.start(0)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"http://127.0.0.1:{proxy.port}/v1/messages",
                    data="not json",
                    headers={"authorization": "Bearer tok"},
                ) as response:
                    assert response.status == 400
        finally:
            await proxy.stop()
