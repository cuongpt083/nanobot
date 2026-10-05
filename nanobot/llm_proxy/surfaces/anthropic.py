"""Anthropic Messages Surface for Nanobot LLM Proxy."""

from __future__ import annotations

import json
import uuid
from typing import Any

from aiohttp import web

from nanobot.llm_proxy.budget import BudgetTracker
from nanobot.llm_proxy.keys import ProxyApiKey
from nanobot.llm_proxy.router import ProxyRouter
from nanobot.providers.base import LLMResponse


async def handle_anthropic_messages(
    request: web.Request,
    key: ProxyApiKey,
    budget_tracker: BudgetTracker,
    router: ProxyRouter,
) -> web.StreamResponse:
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"type": "invalid_request_error", "message": "Invalid JSON"}},
            status=400,
        )

    requested_model = body.get("model", "")
    system_prompt = body.get("system", "")
    raw_messages = body.get("messages", [])
    stream = bool(body.get("stream", False))
    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")

    provider, effective_model, err = router.resolve(requested_model, key)
    if err or provider is None:
        return web.json_response(
            {"error": {"type": "not_found_error", "message": err or "Model not found"}},
            status=404,
        )

    allowed, budget_status = budget_tracker.check_budget(key)
    if not allowed:
        return web.json_response(
            {
                "error": {
                    "type": "rate_limit_error",
                    "message": f"Token budget exceeded ({budget_status['used']}/{budget_status['limit']})",
                }
            },
            status=429,
        )

    # Convert Anthropic format into messages list for provider
    messages: list[dict[str, Any]] = []
    if system_prompt:
        if isinstance(system_prompt, list):
            sys_text = "\n".join(b.get("text", "") for b in system_prompt if isinstance(b, dict))
        else:
            sys_text = str(system_prompt)
        messages.append({"role": "system", "content": sys_text})

    for m in raw_messages:
        messages.append(m)

    msg_id = f"msg_{uuid.uuid4().hex[:16]}"
    kwargs: dict[str, Any] = {
        "messages": messages,
        "model": effective_model,
    }
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    if max_tokens is not None:
        kwargs["max_tokens"] = int(max_tokens)

    if stream:
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        # 1. message_start
        start_event = {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": requested_model,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        }
        await response.write(f"event: message_start\ndata: {json.dumps(start_event)}\n\n".encode("utf-8"))

        # 2. content_block_start
        block_start = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
        await response.write(f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n".encode("utf-8"))

        async def _on_content_delta(delta: str) -> None:
            if not delta:
                return
            ev = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": delta},
            }
            await response.write(f"event: content_block_delta\ndata: {json.dumps(ev)}\n\n".encode("utf-8"))

        res: LLMResponse = await provider.chat_stream_with_retry(
            **kwargs,
            on_content_delta=_on_content_delta,
        )

        # 3. content_block_stop
        await response.write(b"event: content_block_stop\ndata: {\"type\": \"content_block_stop\", \"index\": 0}\n\n")

        # 4. message_delta
        in_toks = res.usage.input_tokens if res.usage else 0
        out_toks = res.usage.output_tokens if res.usage else 0
        tot_toks = res.usage.total_tokens if res.usage else (in_toks + out_toks)

        msg_delta = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": out_toks},
        }
        await response.write(f"event: message_delta\ndata: {json.dumps(msg_delta)}\n\n".encode("utf-8"))

        # 5. message_stop
        await response.write(b"event: message_stop\ndata: {\"type\": \"message_stop\"}\n\n")

        if tot_toks:
            budget_tracker.commit_tokens(key, tot_toks)

        return response

    # Non-streaming
    res = await provider.chat_stream_with_retry(**kwargs)
    in_toks = res.usage.input_tokens if res.usage else 0
    out_toks = res.usage.output_tokens if res.usage else 0
    tot_toks = res.usage.total_tokens if res.usage else (in_toks + out_toks)

    if tot_toks:
        budget_tracker.commit_tokens(key, tot_toks)

    return web.json_response({
        "id": msg_id,
        "type": "message",
        "role": "assistant",
        "model": requested_model,
        "content": [
            {
                "type": "text",
                "text": res.content or "",
            }
        ],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": in_toks,
            "output_tokens": out_toks,
        },
    })
