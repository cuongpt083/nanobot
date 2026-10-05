"""OpenAI Chat Completions Surface for Nanobot LLM Proxy."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from aiohttp import web

from nanobot.llm_proxy.budget import BudgetTracker
from nanobot.llm_proxy.keys import ProxyApiKey
from nanobot.llm_proxy.router import ProxyRouter
from nanobot.providers.base import LLMResponse


async def handle_openai_chat(
    request: web.Request,
    key: ProxyApiKey,
    budget_tracker: BudgetTracker,
    router: ProxyRouter,
) -> web.StreamResponse:
    try:
        body = await request.json()
    except Exception:
        return web.json_response(
            {"error": {"message": "Invalid JSON body", "type": "invalid_request_error"}},
            status=400,
        )

    requested_model = body.get("model", "")
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))
    temperature = body.get("temperature")
    max_tokens = body.get("max_tokens")
    tools = body.get("tools")

    provider, effective_model, err = router.resolve(requested_model, key)
    if err or provider is None:
        return web.json_response(
            {"error": {"message": err or "Model resolution failed", "type": "invalid_request_error"}},
            status=404,
        )

    # Budget gating
    allowed, budget_status = budget_tracker.check_budget(key)
    if not allowed:
        return web.json_response(
            {
                "error": {
                    "message": f"Token budget exceeded for period {budget_status['period']}. Limit: {budget_status['limit']}, used: {budget_status['used']}",
                    "type": "insufficient_quota",
                    "code": 429,
                }
            },
            status=429,
        )

    call_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    kwargs: dict[str, Any] = {
        "messages": messages,
        "tools": tools,
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

        async def _on_content_delta(delta: str) -> None:
            if not delta:
                return
            chunk = {
                "id": call_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": requested_model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": delta},
                        "finish_reason": None,
                    }
                ],
            }
            await response.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))

        res: LLMResponse = await provider.chat_stream_with_retry(
            **kwargs,
            on_content_delta=_on_content_delta,
        )

        final_chunk = {
            "id": call_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": requested_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": res.finish_reason or "stop",
                }
            ],
            "usage": {
                "prompt_tokens": res.usage.input_tokens if res.usage else 0,
                "completion_tokens": res.usage.output_tokens if res.usage else 0,
                "total_tokens": res.usage.total_tokens if res.usage else 0,
            },
        }
        await response.write(f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
        await response.write(b"data: [DONE]\n\n")

        # Commit budget tokens
        if res.usage and res.usage.total_tokens:
            budget_tracker.commit_tokens(key, res.usage.total_tokens)

        return response

    # Non-streaming
    res = await provider.chat_stream_with_retry(**kwargs)
    usage_dict = {
        "prompt_tokens": res.usage.input_tokens if res.usage else 0,
        "completion_tokens": res.usage.output_tokens if res.usage else 0,
        "total_tokens": res.usage.total_tokens if res.usage else 0,
    }

    if res.usage and res.usage.total_tokens:
        budget_tracker.commit_tokens(key, res.usage.total_tokens)

    return web.json_response({
        "id": call_id,
        "object": "chat.completion",
        "created": created,
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": res.content or "",
                },
                "finish_reason": res.finish_reason or "stop",
            }
        ],
        "usage": usage_dict,
    })
