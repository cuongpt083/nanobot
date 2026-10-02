"""Google Antigravity provider — direct OAuth client for Cloud Code Assist.

Speaks the ``v1internal`` Gemini/cloudcode wire protocol used by ``agy`` (see
``docs/plan-google-antigravity-provider.md`` §1). Everything the reference
``pi-ai`` implementation does inline — the ``{project, model, request, …}``
wrapper, the ``agy`` User-Agent/Client-Metadata identity, the Antigravity system
prelude and model-id normalisation — is implemented here directly; there is no
local proxy. The volatile identity surface lives in :mod:`antigravity_adapter`.

.. warning::
   Impersonating the ``agy`` client to use a Google subscription from a
   third-party app may violate Google's terms of service. Prefer Google AI
   Studio / Vertex AI API keys. Disabled by default; for study on accounts you own.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast

import httpx
from loguru import logger

from nanobot.providers.antigravity_adapter import (
    AntigravityAdapter,
    adapter_with_version_floor,
    apply_overrides,
    build_headers,
    normalize_model_id,
)
from nanobot.providers.antigravity_oauth import (
    AntigravityOAuthError,
    AntigravityOAuthReauthRequiredError,
    AntigravityToken,
    get_antigravity_oauth_token,
)
from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ToolCallRequest,
    resolve_stream_idle_timeout_s,
    tool_arguments_object_for_replay,
)

_STREAM_PATH = "/v1internal:streamGenerateContent?alt=sse"
_SKIP_THOUGHT_SIGNATURE = "skip_thought_signature_validator"
_tool_id_counter = 0
_VALID_TOOL_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

_THINKING_BUDGETS = {"minimal": 1024, "low": 2048, "medium": 8192, "high": 16384}


def _gen_tool_id(name: str) -> str:
    global _tool_id_counter
    _tool_id_counter += 1
    return f"{name}_{int(time.time() * 1000)}_{_tool_id_counter}"


def _sanitize_tool_id(value: str) -> str:
    if value and _VALID_TOOL_ID.match(value):
        return value[:64]
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", value or "tool")[:64]
    return safe or "tool"


def _is_gemini3(model: str) -> bool:
    lowered = model.lower()
    return bool(re.search(r"gemini-3(?:\.1)?-(?:pro|flash)", lowered))


def _needs_thought_signature(model: str) -> bool:
    """Any Gemini 3.x model requires a thought signature on replayed function calls.

    Google validates ``thoughtSignature`` on every ``functionCall`` part in the
    conversation history for the whole Gemini 3 family (3, 3.1, 3.6, 3.7, 3.8 …),
    so the check must be broad — matching the reference ``id.includes("gemini-3")``.
    When we do not have the model's real signature we send the
    ``skip_thought_signature_validator`` sentinel to bypass validation.
    """

    return "gemini-3" in model.lower()


def _is_gemini3_pro(model: str) -> bool:
    return bool(re.search(r"gemini-3(?:\.1)?-pro", model.lower()))


def _is_gemini3_flash(model: str) -> bool:
    return bool(re.search(r"gemini-3(?:\.1)?-flash", model.lower()))


def _requires_tool_call_id(model: str) -> bool:
    lowered = model.lower()
    return lowered.startswith("claude-") or lowered.startswith("gpt-oss-")


def _thinking_level(effort: str, model: str) -> str:
    if _is_gemini3_pro(model):
        return "LOW" if effort in ("minimal", "low") else "HIGH"
    return {"minimal": "MINIMAL", "low": "LOW", "medium": "MEDIUM", "high": "HIGH"}.get(
        effort, "MEDIUM"
    )


def _thinking_config(model: str, reasoning_effort: str | None) -> dict[str, Any] | None:
    effort = (reasoning_effort or "").lower()
    enabled = effort not in ("", "none")
    if enabled:
        config: dict[str, Any] = {"includeThoughts": True}
        if _is_gemini3(model):
            config["thinkingLevel"] = _thinking_level(effort, model)
        else:
            config["thinkingBudget"] = _THINKING_BUDGETS.get(effort, 4096)
        return config
    # Disabled: Gemini 3 removed full thinking-off, so use the lowest level.
    if _is_gemini3_pro(model):
        return {"thinkingLevel": "LOW"}
    if _is_gemini3_flash(model):
        return {"thinkingLevel": "MINIMAL"}
    if model.lower().startswith("gemini-2"):
        return {"thinkingBudget": 0}
    return None


class AntigravityProvider(LLMProvider):
    """LLM provider for Google Antigravity via subscription OAuth."""

    def __init__(
        self,
        *,
        default_model: str = "google-antigravity/gemini-3-pro-low",
        provider_name: str = "google_antigravity",
        adapter: AntigravityAdapter | None = None,
        proxy: str | None = None,
    ) -> None:
        adapter = adapter_with_version_floor(adapter or AntigravityAdapter())
        super().__init__(None, adapter.endpoint, provider_name=provider_name)
        self.default_model = default_model
        self._adapter = adapter
        self._proxy = proxy or adapter.proxy
        self._http_client: httpx.AsyncClient | None = None

    # ── helpers ──

    def _strip_prefix(self, model: str) -> str:
        if "/" not in model:
            return model
        prefix, bare = model.split("/", 1)
        if not bare:
            return model
        known = {"google-antigravity", "google_antigravity", self.provider_name.replace("-", "_")}
        if prefix.replace("-", "_").lower() in known:
            return bare
        return model

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            kwargs: dict[str, Any] = {
                "timeout": httpx.Timeout(
                    connect=20.0,
                    read=resolve_stream_idle_timeout_s(),
                    write=60.0,
                    pool=20.0,
                ),
                "trust_env": not bool(self._proxy),
            }
            if self._proxy:
                kwargs["proxy"] = self._proxy
            self._http_client = httpx.AsyncClient(**kwargs)
        return self._http_client

    async def aclose(self) -> None:
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._http_client = None

    # ── conversion ──

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            chunks: list[str] = []
            for part in cast(list[Any], value):
                if isinstance(part, dict):
                    text = cast(dict[str, Any], part).get("text", "")
                    chunks.append(text if isinstance(text, str) else str(text))
                else:
                    chunks.append(str(part))
            return "".join(chunks)
        return str(value)

    def _system_text(self, messages: list[dict[str, Any]]) -> str:
        chunks = [
            self._stringify(msg.get("content")).strip()
            for msg in messages
            if msg.get("role") == "system"
        ]
        return "\n\n".join(chunk for chunk in chunks if chunk)

    def _user_parts(self, content: Any) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        if isinstance(content, str):
            if content:
                parts.append({"text": content})
            return parts or [{"text": "(empty)"}]
        for item in cast(list[Any], content or []):
            if not isinstance(item, dict):
                parts.append({"text": str(item)})
                continue
            block = cast(dict[str, Any], item)
            if block.get("type") == "image_url":
                url = cast(dict[str, Any], block.get("image_url") or {}).get("url", "")
                match = re.match(r"data:(image/\w+);base64,(.+)", url or "", re.DOTALL)
                if match:
                    parts.append(
                        {"inlineData": {"mimeType": match.group(1), "data": match.group(2)}}
                    )
                continue
            text = block.get("text")
            if isinstance(text, str) and text:
                parts.append({"text": text})
        return parts or [{"text": "(empty)"}]

    def _assistant_parts(self, msg: dict[str, Any], model: str) -> list[dict[str, Any]]:
        parts: list[dict[str, Any]] = []
        text = self._stringify(msg.get("content"))
        if text and text.strip():
            parts.append({"text": text})
        needs_id = _requires_tool_call_id(model)
        needs_signature = _needs_thought_signature(model)
        for raw in cast(list[Any], msg.get("tool_calls") or []):
            if not isinstance(raw, dict):
                continue
            call = cast(dict[str, Any], raw)
            func = cast(dict[str, Any], call.get("function") or {})
            args = tool_arguments_object_for_replay(func.get("arguments", "{}"))
            part: dict[str, Any] = {
                "functionCall": {
                    "name": func.get("name", ""),
                    "args": args,
                    **({"id": _sanitize_tool_id(str(call.get("id")))} if needs_id and call.get("id") else {}),
                }
            }
            if needs_signature:
                part["thoughtSignature"] = _SKIP_THOUGHT_SIGNATURE
            parts.append(part)
        return parts or [{"text": ""}]

    def _convert_messages(self, messages: list[dict[str, Any]], model: str) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        needs_id = _requires_tool_call_id(model)
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                continue
            if role == "user":
                contents.append({"role": "user", "parts": self._user_parts(msg.get("content"))})
            elif role == "assistant":
                parts = self._assistant_parts(msg, model)
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                response_value = self._stringify(msg.get("content"))
                function_response: dict[str, Any] = {
                    "name": msg.get("name") or "",
                    "response": (
                        {"error": response_value} if msg.get("is_error") else {"output": response_value}
                    ),
                }
                if needs_id and msg.get("tool_call_id"):
                    function_response["id"] = _sanitize_tool_id(str(msg.get("tool_call_id")))
                part = {"functionResponse": function_response}
                # Cloud Code Assist requires all function responses in one user turn.
                if contents and contents[-1]["role"] == "user" and any(
                    "functionResponse" in p for p in contents[-1]["parts"]
                ):
                    contents[-1]["parts"].append(part)
                else:
                    contents.append({"role": "user", "parts": [part]})
        return contents

    @staticmethod
    def _tool_name(tool: dict[str, Any]) -> str:
        name = tool.get("name")
        if isinstance(name, str):
            return name
        func = tool.get("function")
        if isinstance(func, dict):
            return cast(dict[str, Any], func).get("name", "")
        return ""

    def _convert_tools(self, tools: list[dict[str, Any]] | None, model: str) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        use_parameters = model.lower().startswith("claude-")
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            func = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            func = cast(dict[str, Any], func)
            entry: dict[str, Any] = {"name": func.get("name", "")}
            if func.get("description"):
                entry["description"] = func["description"]
            schema = func.get("parameters", {"type": "object", "properties": {}})
            entry["parameters" if use_parameters else "parametersJsonSchema"] = schema
            declarations.append(entry)
        return [{"functionDeclarations": declarations}]

    @staticmethod
    def _map_tool_choice(choice: str | dict[str, Any] | None) -> str:
        if choice == "none":
            return "NONE"
        if choice in ("required", "any"):
            return "ANY"
        if isinstance(choice, dict):
            return "ANY"
        return "AUTO"

    def _build_wrapper(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        project_id: str,
    ) -> dict[str, Any]:
        adapter = self._adapter
        wire_model = normalize_model_id(self._strip_prefix(model), adapter.model_aliases)
        contents = self._convert_messages(messages, wire_model)

        request: dict[str, Any] = {"contents": contents}

        system_text = self._system_text(messages)
        system_parts: list[dict[str, Any]] = []
        if system_text:
            system_parts.append({"text": system_text})
        if adapter.inject_system_instruction:
            from nanobot.providers.antigravity_adapter import ANTIGRAVITY_SYSTEM_INSTRUCTION

            prelude = [
                {"text": ANTIGRAVITY_SYSTEM_INSTRUCTION},
                {"text": f"Please ignore following [ignore]{ANTIGRAVITY_SYSTEM_INSTRUCTION}[/ignore]"},
            ]
            request["systemInstruction"] = {"role": "user", "parts": [*prelude, *system_parts]}
        elif system_parts:
            request["systemInstruction"] = {"parts": system_parts}

        generation_config: dict[str, Any] = {}
        generation_config["temperature"] = temperature
        generation_config["maxOutputTokens"] = max(1, max_tokens)
        thinking = _thinking_config(wire_model, reasoning_effort)
        if thinking is not None:
            generation_config["thinkingConfig"] = thinking
        request["generationConfig"] = generation_config

        converted_tools = self._convert_tools(tools, wire_model)
        if converted_tools:
            request["tools"] = converted_tools
            request["toolConfig"] = {
                "functionCallingConfig": {"mode": self._map_tool_choice(tool_choice)}
            }

        wrapper = {
            "project": project_id,
            "model": wire_model,
            "request": request,
            "requestType": adapter.request_type,
            "userAgent": adapter.user_agent_label,
            "requestId": f"{adapter.request_type}-{int(time.time() * 1000)}-{secrets.token_hex(4)}",
        }
        return apply_overrides(wrapper, adapter)

    # ── request ──

    async def _run(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        *,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        adapter = self._adapter
        selected_model = model or self.default_model
        wire_model = normalize_model_id(self._strip_prefix(selected_model), adapter.model_aliases)
        try:
            token = get_antigravity_oauth_token(adapter=adapter, proxy=self._proxy)
        except AntigravityOAuthReauthRequiredError as exc:
            return LLMResponse(
                content=f"Error calling LLM: {exc}",
                finish_reason="error",
                error_kind="oauth_auth_required",
                error_should_retry=False,
            )
        except AntigravityOAuthError as exc:
            return LLMResponse(content=f"Error calling LLM: {exc}", finish_reason="error")

        if not token.project_id:
            return LLMResponse(
                content=(
                    "Error calling LLM: Antigravity credentials are missing a project id. "
                    "Run `nanobot provider login google-antigravity` again."
                ),
                finish_reason="error",
                error_kind="oauth_auth_required",
                error_should_retry=False,
            )

        sanitized = self._sanitize_empty_content(messages)
        wrapper = self._build_wrapper(
            sanitized, tools, selected_model, max_tokens, temperature, reasoning_effort, tool_choice,
            token.project_id,
        )
        reasoning_claude = wire_model.lower().startswith("claude-") and (
            reasoning_effort is not None and reasoning_effort.lower() not in ("", "none")
        )
        headers = build_headers(adapter, token.access, reasoning_claude=reasoning_claude)

        try:
            return await self._stream(token, wrapper, headers, wire_model, on_content_delta, on_thinking_delta, on_tool_call_delta)
        except httpx.HTTPStatusError as exc:
            return self._http_error_response(exc)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return LLMResponse(
                content=f"Error calling LLM: {exc}",
                finish_reason="error",
                error_kind="timeout" if isinstance(exc, httpx.TimeoutException) else "connection",
            )

    async def _stream(
        self,
        token: AntigravityToken,
        wrapper: dict[str, Any],
        headers: dict[str, str],
        wire_model: str,
        on_content_delta: Callable[[str], Awaitable[None]] | None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> LLMResponse:
        client = self._client()
        endpoints = self._adapter.target_endpoints
        response: httpx.Response | None = None
        last_error_text = ""
        for index, endpoint in enumerate(endpoints):
            url = f"{endpoint}{_STREAM_PATH}"
            request = client.build_request("POST", url, json=wrapper, headers=headers)
            response = await client.send(request, stream=True)
            if response.status_code < 400:
                break
            last_error_text = (await response.aread()).decode("utf-8", "replace")
            await response.aclose()
            if response.status_code in (403, 404) and index < len(endpoints) - 1:
                logger.info(
                    "Antigravity endpoint {} returned {}; trying next", endpoint, response.status_code
                )
                continue
            raise httpx.HTTPStatusError(
                f"Antigravity API error ({response.status_code})",
                request=request,
                response=httpx.Response(response.status_code, content=last_error_text),
            )

        if response is None:
            raise httpx.TransportError("no Antigravity endpoint responded")

        content_parts: list[str] = []
        thinking_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        usage: LLMUsage | None = None
        finish_reason = "stop"

        try:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload:
                    continue
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                data = cast(dict[str, Any], chunk).get("response")
                if not isinstance(data, dict):
                    continue
                data = cast(dict[str, Any], data)
                candidate = self._first_candidate(data)
                if candidate is not None:
                    await self._consume_parts(
                        candidate, wire_model, content_parts, thinking_parts, tool_calls,
                        on_content_delta, on_thinking_delta, on_tool_call_delta,
                    )
                    reason = candidate.get("finishReason")
                    if isinstance(reason, str):
                        finish_reason = self._map_finish_reason(reason)
                usage = self._extract_usage(data, usage)
        finally:
            await response.aclose()

        if tool_calls:
            finish_reason = "tool_calls"
        return LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(thinking_parts) or None,
        )

    @staticmethod
    def _first_candidate(data: dict[str, Any]) -> dict[str, Any] | None:
        raw = data.get("candidates")
        if isinstance(raw, list):
            candidates = cast(list[Any], raw)
            if candidates and isinstance(candidates[0], dict):
                return cast(dict[str, Any], candidates[0])
        return None

    async def _consume_parts(
        self,
        candidate: dict[str, Any],
        wire_model: str,
        content_parts: list[str],
        thinking_parts: list[str],
        tool_calls: list[ToolCallRequest],
        on_content_delta: Callable[[str], Awaitable[None]] | None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> None:
        content = candidate.get("content")
        if not isinstance(content, dict):
            return
        parts = cast(dict[str, Any], content).get("parts")
        if not isinstance(parts, list):
            return
        for raw in cast(list[Any], parts):
            if not isinstance(raw, dict):
                continue
            part = cast(dict[str, Any], raw)
            text = part.get("text")
            if isinstance(text, str) and text:
                if part.get("thought") is True:
                    thinking_parts.append(text)
                    if on_thinking_delta is not None:
                        await on_thinking_delta(text)
                else:
                    content_parts.append(text)
                    if on_content_delta is not None:
                        await on_content_delta(text)
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                call = cast(dict[str, Any], function_call)
                name = call.get("name", "")
                provided_id = call.get("id")
                call_id = (
                    str(provided_id)
                    if isinstance(provided_id, str) and provided_id
                    else _gen_tool_id(name)
                )
                args = call.get("args")
                arguments: dict[str, Any] = (
                    cast(dict[str, Any], args) if isinstance(args, dict) else {}
                )
                tool_calls.append(
                    ToolCallRequest(id=call_id, name=name, arguments=arguments)
                )
                if on_tool_call_delta is not None:
                    await on_tool_call_delta(
                        {
                            "index": len(tool_calls) - 1,
                            "call_id": call_id,
                            "name": name,
                            "arguments_delta": json.dumps(arguments),
                        }
                    )

    @staticmethod
    def _map_finish_reason(reason: str) -> str:
        if reason == "STOP":
            return "stop"
        if reason == "MAX_TOKENS":
            return "length"
        return "error"

    @staticmethod
    def _extract_usage(data: dict[str, Any], previous: LLMUsage | None) -> LLMUsage | None:
        meta = data.get("usageMetadata")
        if not isinstance(meta, dict):
            return previous
        meta = cast(dict[str, Any], meta)
        prompt = int(meta.get("promptTokenCount") or 0)
        cached = int(meta.get("cachedContentTokenCount") or 0)
        output = int(meta.get("candidatesTokenCount") or 0) + int(
            meta.get("thoughtsTokenCount") or 0
        )
        total = int(meta.get("totalTokenCount") or 0)
        if prompt == 0 and output == 0 and total == 0:
            return previous
        # nanobot's `input_tokens` is the *logical input total* and already
        # includes cache reads, so it maps to `promptTokenCount` directly (not
        # `promptTokenCount - cachedContentTokenCount`). Clamp the cached count
        # so the LLMUsage invariant (cache_total <= input_tokens) always holds.
        cached = min(max(cached, 0), prompt)
        return LLMUsage.reported(
            input_tokens=prompt,
            output_tokens=output,
            total_tokens=total or None,
            cache_read_tokens=cached,
        )

    def _http_error_response(self, exc: httpx.HTTPStatusError) -> LLMResponse:
        status = exc.response.status_code
        body = exc.response.text
        message = self._extract_error_message(body) or str(exc)
        return LLMResponse(
            content=f"Error calling LLM: Antigravity API error ({status}): {message}",
            finish_reason="error",
            error_status_code=status,
        )

    @staticmethod
    def _extract_error_message(body: str) -> str:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                error = cast(dict[str, Any], parsed).get("error")
                if isinstance(error, dict):
                    message = cast(dict[str, Any], error).get("message")
                    if isinstance(message, str):
                        return message
                if isinstance(error, str):
                    return error
        except (json.JSONDecodeError, TypeError):
            pass
        return body[:500]

    # ── public API ──

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        return await self._run(
            messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice
        )

    async def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_thinking_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_call_delta: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        return await self._run(
            messages, tools, model, max_tokens, temperature, reasoning_effort, tool_choice,
            on_content_delta=on_content_delta,
            on_thinking_delta=on_thinking_delta,
            on_tool_call_delta=on_tool_call_delta,
        )

    def get_default_model(self) -> str:
        return self.default_model
