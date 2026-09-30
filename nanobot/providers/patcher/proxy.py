"""Anthropic OAuth patcher proxy — local HTTP proxy for the OAuth bypass.

Intercepts Anthropic Messages-API requests, applies configurable patch rules
(system-prompt cleaning, tool renaming, header fixing), forwards to the real API
and reverse-patches responses (tool names + text patterns) so the runtime keeps
working.

The proxy is deliberately transport-thin: all behaviour lives in data
(:mod:`nanobot.providers.patcher.rules`) and the SSE logic in
:mod:`nanobot.providers.patcher.sse`. Upstream socket handling mirrors the
original resilience decisions:

* happy-eyeballs window widened,
* connect timeout separate from a generous response-headers timeout,
* retry only pre-response connection failures (never a header timeout).
"""

from __future__ import annotations

import errno as errno_module
import json
import socket
import uuid
from typing import Any, cast

import aiohttp
from aiohttp import web
from loguru import logger

from nanobot.providers.patcher.rules import (
    PatcherConfig,
    PatcherRule,
    apply_rules,
    build_tool_name_maps,
    default_config,
    render_template,
    rules_by_category,
)
from nanobot.providers.patcher.sse import create_anthropic_sse_reframer

LOG_TAG = "[Anthropic-Patcher]"

#: Per-address-family connect window (Node's default is a stingy 250ms).
UPSTREAM_CONNECT_ATTEMPT_TIMEOUT_MS = 1500
#: TCP/TLS connect deadline.
UPSTREAM_CONNECT_TIMEOUT_S = 20.0
#: Response-headers deadline after the socket is up. Anthropic's time-to-first-byte
#: on multi-MB prompts can run minutes, so this is generous AND not retryable.
UPSTREAM_HEADERS_TIMEOUT_S = 600.0
#: Extra attempts when the connection fails *before* any response byte arrives.
UPSTREAM_CONNECT_MAX_RETRIES = 2

NETWORK_CODE_HINTS: dict[str, str] = {
    "ENETUNREACH": "network unreachable — no route to the internet",
    "EHOSTUNREACH": "host unreachable — no route to the internet",
    "ENETDOWN": "network interface is down",
    "ENOTFOUND": "DNS lookup failed",
    "EAI_AGAIN": "DNS lookup failed (temporary)",
    "ECONNREFUSED": "connection refused",
    "ECONNRESET": "connection reset by peer",
    "ETIMEDOUT": "connection timed out",
    "EPIPE": "connection closed while sending",
    "UPSTREAM_HEADERS_TIMEOUT": "upstream accepted the connection but never answered",
}

RETRYABLE_CONNECT_CODES = frozenset(
    {
        "ETIMEDOUT",
        "ECONNRESET",
        "ECONNREFUSED",
        "EAI_AGAIN",
        "ENETUNREACH",
        "EHOSTUNREACH",
        "EPIPE",
    }
)


# ── Upstream error diagnostics ──


def _errno_name(value: int) -> str | None:
    """Resolve a numeric errno to a POSIX-style symbolic name.

    On Windows the C runtime reports Winsock codes (``WSAETIMEDOUT``,
    ``WSAENETUNREACH``, …); strip the ``WSA`` prefix so callers can match the
    same portable names the original Node proxy used.
    """

    name = errno_module.errorcode.get(value)
    if name is None:
        for module in (errno_module, socket):
            for attr in dir(module):
                if attr.isupper() and getattr(module, attr, None) == value:
                    name = attr
                    break
            if name is not None:
                break
    if name is None:
        return None
    return name[3:] if name.startswith("WSA") else name


def collect_error_codes(err: object) -> list[str]:
    """Collect every network code reachable from ``err`` (cause chain + os_error)."""

    codes: list[str] = []
    seen: set[int] = set()
    stack: list[object] = [err]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno:
            name = _errno_name(current.errno)
            if name and name not in codes:
                codes.append(name)
        os_error = getattr(current, "os_error", None)
        if os_error is not None and os_error is not current:
            stack.append(os_error)
        for attr in ("__cause__", "__context__"):
            inner = getattr(current, attr, None)
            if inner is not None:
                stack.append(inner)
    return codes


def describe_upstream_error(err: object, host: str) -> tuple[str, str]:
    """Turn an upstream failure into a ``(type, message)`` a human can act on."""

    codes = collect_error_codes(err)
    primary = codes[0] if codes else None
    if primary and primary in NETWORK_CODE_HINTS:
        return (
            "network_error",
            f"Cannot reach {host}: {'/'.join(codes)} ({NETWORK_CODE_HINTS[primary]}). "
            "Check your internet connection, VPN or DNS, then try again.",
        )
    base = str(err) if not isinstance(err, BaseException) or not str(err) else str(err)
    return ("proxy_error", f"{base} [{ '/'.join(codes) }]" if codes else base)


def is_retryable_connect_error(err: object) -> bool:
    """True for pre-response connection failures that are safe to re-send."""

    return any(code in RETRYABLE_CONNECT_CODES for code in collect_error_codes(err))


# ── Pure request/response transforms (unit-testable without a socket) ──


def transform_system_blocks(
    blocks: list[dict[str, Any]],
    rules: list[PatcherRule],
    *,
    attribution_template: str,
    claude_code_version: str,
) -> list[dict[str, Any]]:
    """Apply ``system`` rules to each text block, then inject attribution at [0]."""

    transformed: list[dict[str, object]] = []
    for raw in blocks:
        block = cast(dict[str, object], raw)
        text = block.get("text")
        if isinstance(text, str):
            new_text = apply_rules(text, rules)
            transformed.append({**block, "text": new_text} if new_text != text else block)
        else:
            transformed.append(block)

    if attribution_template:
        attribution = render_template(attribution_template, version=claude_code_version)
        first_text = transformed[0].get("text") if transformed else None
        already = isinstance(first_text, str) and first_text.startswith(
            "x-anthropic-billing-header"
        )
        if not already:
            transformed.insert(0, {"type": "text", "text": attribution})
    return cast(list[dict[str, Any]], transformed)


def transform_tools(tools: list[dict[str, Any]], rules: list[PatcherRule]) -> list[dict[str, Any]]:
    """Rename tools via ``tool_name`` rules and clean descriptions."""

    name_rules = rules_by_category(rules, "tool_name")
    desc_rules = rules_by_category(rules, "tool_desc")
    request_map, _ = build_tool_name_maps(name_rules)

    result: list[dict[str, object]] = []
    for raw in tools:
        tool = cast(dict[str, object], raw)
        patched = dict(tool)
        name = patched.get("name")
        if isinstance(name, str) and name in request_map:
            patched["name"] = request_map[name]
        description = patched.get("description")
        if isinstance(description, str) and desc_rules:
            patched["description"] = apply_rules(description, desc_rules)
        result.append(patched)
    return cast(list[dict[str, Any]], result)


def transform_request(config: PatcherConfig, body: dict[str, Any]) -> dict[str, Any]:
    """Apply every request-side transformation."""

    result = cast(dict[str, object], dict(body))
    rules = config.rules
    system = result.get("system")
    if isinstance(system, list):
        result["system"] = transform_system_blocks(
            cast(list[dict[str, Any]], system),
            rules_by_category(rules, "system"),
            attribution_template=config.attribution_template,
            claude_code_version=config.claude_code_version,
        )
    tools = result.get("tools")
    if isinstance(tools, list):
        result["tools"] = transform_tools(cast(list[dict[str, Any]], tools), rules)
    return cast(dict[str, Any], result)


def build_upstream_headers(config: PatcherConfig, incoming: dict[str, str], session_id: str) -> dict[str, str]:
    """Build headers from scratch (never pass browser/CLI fingerprints through)."""

    headers: dict[str, str] = {}
    authorization = incoming.get("authorization")
    if authorization:
        headers["authorization"] = authorization
    anthropic_version = incoming.get("anthropic-version")
    if anthropic_version:
        headers["anthropic-version"] = anthropic_version
    headers["content-type"] = "application/json"

    for rule in rules_by_category(config.rules, "header"):
        value = render_template(
            rule.replace, version=config.claude_code_version, session_id=session_id
        )
        name = rule.find.lower()
        if value == "":
            headers.pop(name, None)
        else:
            headers[name] = value

    if config.add_session_id:
        headers["x-claude-code-session-id"] = session_id
    return headers


def reverse_sse_event(
    event: dict[str, Any],
    response_map: dict[str, str],
    response_rules: list[PatcherRule],
) -> dict[str, Any]:
    """Reverse-patch a single SSE event object (drop-in from the original)."""

    event_type_value = cast(dict[str, object], event).get("type")
    event_type = event_type_value if isinstance(event_type_value, str) else None

    if event_type == "content_block_start":
        block_value = event.get("content_block")
        if isinstance(block_value, dict):
            block = cast(dict[str, object], block_value)
            if block.get("type") == "tool_use":
                name = block.get("name")
                if isinstance(name, str) and name in response_map:
                    return {**event, "content_block": {**block, "name": response_map[name]}}
    elif event_type == "content_block_delta":
        delta_value = event.get("delta")
        if isinstance(delta_value, dict):
            delta = cast(dict[str, object], delta_value)
            if delta.get("type") == "text_delta":
                text = delta.get("text")
                if isinstance(text, str):
                    reversed_text = apply_rules(text, response_rules)
                    if reversed_text != text:
                        return {**event, "delta": {**delta, "text": reversed_text}}
    elif event_type == "message_start":
        message_value = event.get("message")
        if isinstance(message_value, dict):
            message = cast(dict[str, object], message_value)
            content_value = message.get("content")
            if isinstance(content_value, list):
                return {
                    **event,
                    "message": {
                        **message,
                        "content": _reverse_content(
                            cast(list[dict[str, Any]], content_value),
                            response_map,
                            response_rules,
                        ),
                    },
                }

    return event


def _reverse_content(
    content: list[dict[str, Any]],
    response_map: dict[str, str],
    response_rules: list[PatcherRule],
) -> list[dict[str, Any]]:
    patched: list[dict[str, Any]] = []
    for raw_block in content:
        block = cast(dict[str, object], raw_block)
        block_type = block.get("type")
        if block_type == "tool_use":
            new_block: dict[str, object] = dict(block)
            name = new_block.get("name")
            if isinstance(name, str) and name in response_map:
                new_block["name"] = response_map[name]
            tool_input = new_block.get("input")
            if isinstance(tool_input, dict) and response_rules:
                input_str = json.dumps(tool_input)
                reversed_str = apply_rules(input_str, response_rules)
                if reversed_str != input_str:
                    try:
                        new_block["input"] = json.loads(reversed_str)
                    except json.JSONDecodeError:
                        pass
            patched.append(cast(dict[str, Any], new_block))
        elif block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                reversed_text = apply_rules(text, response_rules)
                patched.append(
                    {**raw_block, "text": reversed_text} if reversed_text != text else raw_block
                )
            else:
                patched.append(raw_block)
        else:
            patched.append(raw_block)
    return patched


def reverse_full_response(
    response: dict[str, Any],
    response_map: dict[str, str],
    response_rules: list[PatcherRule],
) -> dict[str, Any]:
    """Reverse-patch a full (non-streaming) Messages-API response."""

    content_value = cast(dict[str, object], response).get("content")
    if not isinstance(content_value, list):
        return response
    return {
        **response,
        "content": _reverse_content(
            cast(list[dict[str, Any]], content_value), response_map, response_rules
        ),
    }


# ── Proxy ──


class AnthropicPatcherProxy:
    """Local ``127.0.0.1`` HTTP proxy implementing the OAuth patcher."""

    def __init__(self, config: PatcherConfig | None = None) -> None:
        self.config = config or default_config()
        self.session_id = str(uuid.uuid4())
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._session: aiohttp.ClientSession | None = None
        self._port = 0
        self._running = False

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._running

    def reload_config(self, config: PatcherConfig) -> None:
        self.config = config
        logger.info(f"{LOG_TAG} Config reloaded ({len(config.rules)} rules)")

    async def start(self, port: int | None = None) -> int:
        if self._running:
            return self._port

        listen_port = port if port is not None else self.config.port
        app = web.Application()
        app.router.add_route("POST", "/{tail:.*}", self._handle)
        app.router.add_route("GET", "/health", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(
                total=None,
                connect=UPSTREAM_CONNECT_TIMEOUT_S,
                sock_read=UPSTREAM_HEADERS_TIMEOUT_S,
            )
        )
        self._site = web.TCPSite(self._runner, "127.0.0.1", listen_port)
        await self._site.start()
        server = self._site._server  # pyright: ignore[reportPrivateUsage] — aiohttp exposes no public accessor
        sockets = getattr(server, "sockets", None) if server is not None else None
        if sockets:
            self._port = int(sockets[0].getsockname()[1])
        else:
            self._port = listen_port
        self._running = True
        logger.info(f"{LOG_TAG} Listening on 127.0.0.1:{self._port}")
        return self._port

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._session is not None:
            await self._session.close()
            self._session = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self._site = None
        logger.info(f"{LOG_TAG} Stopped")

    # ── HTTP handlers ──

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "rules": len(self.config.rules)})

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        try:
            return await self._proxy_request(request)
        except Exception as err:  # noqa: BLE001 — translate every failure into a clean 502
            host = _target_host(self.config.target_base_url)
            error_type, message = describe_upstream_error(err, host)
            logger.error(f"{LOG_TAG} Request error ({error_type}): {message}")
            return web.json_response(
                {"type": "error", "error": {"type": error_type, "message": message}},
                status=502,
            )

    async def _proxy_request(self, request: web.Request) -> web.StreamResponse:
        if self._session is None:
            raise RuntimeError("proxy session is not started")

        body = await request.text()
        try:
            raw = json.loads(body)
        except json.JSONDecodeError:
            return web.json_response(
                {"error": {"message": "Invalid JSON body"}}, status=400
            )
        if not isinstance(raw, dict):
            return web.json_response({"error": {"message": "Invalid JSON body"}}, status=400)
        parsed = cast(dict[str, Any], raw)
        parsed_fields = cast(dict[str, object], raw)

        transformed = transform_request(self.config, parsed)
        upstream_headers = build_upstream_headers(
            self.config, dict(request.headers), self.session_id
        )
        target_url = self.config.target_base_url.rstrip("/") + request.path_qs
        upstream_body = json.dumps(transformed)

        logger.info(f"{LOG_TAG} → {target_url} ({len(upstream_body) / 1024:.1f}KB)")
        upstream = await self._open_upstream(target_url, upstream_headers, upstream_body)

        content_type = upstream.headers.get("content-type", "")
        is_streaming = (
            parsed_fields.get("stream") is not False and "text/event-stream" in content_type
        )

        if is_streaming:
            return await self._stream_response(request, upstream)
        return await self._json_response(upstream)

    async def _open_upstream(
        self, target_url: str, headers: dict[str, str], body: str
    ) -> aiohttp.ClientResponse:
        assert self._session is not None
        last_error: BaseException | None = None
        for attempt in range(UPSTREAM_CONNECT_MAX_RETRIES + 1):
            try:
                return await self._session.post(target_url, headers=headers, data=body)
            except (aiohttp.ClientError, TimeoutError, OSError) as err:
                last_error = err
                if attempt < UPSTREAM_CONNECT_MAX_RETRIES and is_retryable_connect_error(err):
                    logger.warning(
                        f"{LOG_TAG} upstream connect failed; retry "
                        f"{attempt + 1}/{UPSTREAM_CONNECT_MAX_RETRIES}"
                    )
                    continue
                raise
        raise last_error if last_error is not None else RuntimeError("upstream connect failed")

    async def _stream_response(
        self, request: web.Request, upstream: aiohttp.ClientResponse
    ) -> web.StreamResponse:
        response = web.StreamResponse(status=upstream.status)
        for key, value in upstream.headers.items():
            if key.lower() in ("transfer-encoding", "content-length", "connection"):
                continue
            response.headers[key] = value
        await response.prepare(request)

        name_rules = rules_by_category(self.config.rules, "tool_name")
        response_rules = rules_by_category(self.config.rules, "response")
        _, response_map = build_tool_name_maps(name_rules)

        def reverse_event(event: dict[str, Any]) -> dict[str, Any]:
            return reverse_sse_event(event, response_map, response_rules)

        pending: list[str] = []
        reframer = create_anthropic_sse_reframer(
            pending.append,
            reverse_event=reverse_event,
            reverse_tool_input=lambda value: apply_rules(value, response_rules),
            on_reverse_tool_input=lambda index: logger.info(
                f"{LOG_TAG} Reverse-patched tool input (index={index})"
            ),
        )

        async for chunk in upstream.content.iter_any():
            reframer.on_data(chunk)
            if pending:
                await response.write("".join(pending).encode())
                pending.clear()
        reframer.on_end()
        if pending:
            await response.write("".join(pending).encode())
        upstream.release()
        await response.write_eof()
        return response

    async def _json_response(self, upstream: aiohttp.ClientResponse) -> web.StreamResponse:
        raw = await upstream.read()
        upstream.release()
        name_rules = rules_by_category(self.config.rules, "tool_name")
        response_rules = rules_by_category(self.config.rules, "response")
        _, response_map = build_tool_name_maps(name_rules)

        response_body = raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                response_body = json.dumps(
                    reverse_full_response(cast(dict[str, Any], parsed), response_map, response_rules)
                ).encode("utf-8")
        except json.JSONDecodeError:
            pass

        response = web.Response(status=upstream.status, body=response_body)
        for key, value in upstream.headers.items():
            if key.lower() in ("content-length", "transfer-encoding", "connection"):
                continue
            response.headers[key] = value
        return response


def _target_host(base_url: str) -> str:
    from urllib.parse import urlsplit

    try:
        return urlsplit(base_url).hostname or "upstream"
    except ValueError:
        return "upstream"


# ── Singleton ──

_instance: AnthropicPatcherProxy | None = None


def get_patcher_proxy() -> AnthropicPatcherProxy:
    global _instance
    if _instance is None:
        _instance = AnthropicPatcherProxy()
    return _instance


async def start_anthropic_patcher_proxy(
    config: PatcherConfig | None = None,
) -> AnthropicPatcherProxy:
    proxy = get_patcher_proxy()
    if config is not None:
        proxy.reload_config(config)
    if not proxy.is_running:
        await proxy.start()
    return proxy


async def stop_anthropic_patcher_proxy() -> None:
    global _instance
    if _instance is not None:
        await _instance.stop()
        _instance = None
