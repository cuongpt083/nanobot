"""Tests for the patcher proxy transforms, headers and error diagnostics."""

from __future__ import annotations

import errno
import socket
from typing import Any

from nanobot.providers.patcher.proxy import (
    build_upstream_headers,
    collect_error_codes,
    describe_upstream_error,
    is_retryable_connect_error,
    reverse_full_response,
    transform_request,
)
from nanobot.providers.patcher.rules import (
    DEFAULT_ATTRIBUTION,
    PatcherConfig,
    PatcherRule,
    build_tool_name_maps,
    rules_by_category,
)


def _config(**overrides: Any) -> PatcherConfig:
    defaults: dict[str, Any] = {"enabled": True}
    defaults.update(overrides)
    return PatcherConfig(**defaults)


def test_transform_request_applies_system_rules_and_injects_attribution() -> None:
    config = _config(
        claude_code_version="2.1.280",
        attribution_template=DEFAULT_ATTRIBUTION,
        rules=[
            PatcherRule(
                id="brand",
                category="system",
                find="OpenClaw",
                replace="Claude Code",
            )
        ],
    )
    body = {"system": [{"type": "text", "text": "Hello OpenClaw"}], "messages": []}
    result = transform_request(config, body)
    system = result["system"]
    assert isinstance(system, list)
    assert system[0]["text"].startswith("x-anthropic-billing-header")
    assert "cc_version=2.1.280.a1b" in system[0]["text"]
    assert system[1]["text"] == "Hello Claude Code"


def test_transform_request_does_not_duplicate_attribution() -> None:
    config = _config(
        claude_code_version="2.1.280",
        attribution_template=DEFAULT_ATTRIBUTION,
        rules=[],
    )
    body = {
        "system": [{"type": "text", "text": "x-anthropic-billing-header: already"}],
    }
    result = transform_request(config, body)
    system = result["system"]
    assert isinstance(system, list)
    assert len(system) == 1


def test_transform_request_renames_tools_and_cleans_descriptions() -> None:
    config = _config(
        rules=[
            PatcherRule(
                id="t",
                category="tool_name",
                find="sessions_list",
                replace="Sessions_list",
            ),
            PatcherRule(id="d", category="tool_desc", find="OpenClaw", replace="Claude Code"),
        ],
    )
    body = {
        "tools": [
            {
                "name": "sessions_list",
                "description": "List sessions in OpenClaw",
                "input_schema": {"type": "object"},
            }
        ]
    }
    result = transform_request(config, body)
    tools = result["tools"]
    assert isinstance(tools, list)
    assert tools[0]["name"] == "Sessions_list"
    assert tools[0]["description"] == "List sessions in Claude Code"


def test_build_upstream_headers_keeps_only_essentials_and_applies_rules() -> None:
    config = _config(
        claude_code_version="2.1.280",
        add_session_id=True,
        rules=[
            PatcherRule(
                id="ua",
                category="header",
                find="user-agent",
                replace="claude-cli/${version}",
            ),
            PatcherRule(id="accept", category="header", find="accept", replace=""),
        ],
    )
    incoming = {
        "authorization": "Bearer tok",
        "anthropic-version": "2023-06-01",
        "accept": "application/json",
        "anthropic-dangerous-direct-browser-access": "true",
        "content-type": "application/json",
    }
    headers = build_upstream_headers(config, incoming, "session-123")
    assert headers["authorization"] == "Bearer tok"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["user-agent"] == "claude-cli/2.1.280"
    assert "accept" not in headers
    assert "anthropic-dangerous-direct-browser-access" not in headers
    assert headers["x-claude-code-session-id"] == "session-123"


def test_build_upstream_headers_can_disable_session_id() -> None:
    config = _config(add_session_id=False, rules=[])
    headers = build_upstream_headers(config, {}, "s")
    assert "x-claude-code-session-id" not in headers


def test_reverse_full_response_reverts_names_and_input() -> None:
    rules = [
        PatcherRule(
            id="t",
            category="tool_name",
            find="sessions_list",
            replace="Sessions_list",
        ),
        PatcherRule(
            id="r",
            category="response",
            find="Memory_search",
            replace="memory_search",
        ),
    ]
    _, response_map = build_tool_name_maps(rules_by_category(rules, "tool_name"))
    response_rules = rules_by_category(rules, "response")
    response = {
        "content": [
            {"type": "text", "text": "call Memory_search now"},
            {
                "type": "tool_use",
                "name": "Sessions_list",
                "input": {"query": "Memory_search"},
            },
        ]
    }
    result = reverse_full_response(response, response_map, response_rules)
    content = result["content"]
    assert isinstance(content, list)
    assert content[0]["text"] == "call memory_search now"
    assert content[1]["name"] == "sessions_list"
    assert content[1]["input"] == {"query": "memory_search"}


def test_reverse_full_response_passthrough_when_not_json_content() -> None:
    response = {"content": "not-a-list"}
    assert reverse_full_response(response, {}, []) == response


def test_collect_error_codes_unwraps_cause_chain_and_os_error() -> None:
    os_error = OSError(errno.ENETUNREACH, "no route")
    wrapped = ConnectionError(errno.ECONNRESET, "reset")
    wrapped.__cause__ = os_error
    codes = collect_error_codes(wrapped)
    assert "ECONNRESET" in codes
    assert "ENETUNREACH" in codes


def test_collect_error_codes_reads_aiohttp_os_error_attribute() -> None:
    class FakeConnectorError(Exception):
        def __init__(self) -> None:
            super().__init__("boom")
            self.os_error = OSError(socket.EAI_AGAIN, "dns")

    assert "EAI_AGAIN" in collect_error_codes(FakeConnectorError())


def test_describe_upstream_error_prefers_network_hint() -> None:
    err = ConnectionError(errno.ENETUNREACH, "no route")
    error_type, message = describe_upstream_error(err, "api.anthropic.com")
    assert error_type == "network_error"
    assert "api.anthropic.com" in message
    assert "no route to the internet" in message


def test_describe_upstream_error_falls_back_to_proxy_error() -> None:
    error_type, message = describe_upstream_error(ValueError("weird"), "host")
    assert error_type == "proxy_error"
    assert "weird" in message


def test_is_retryable_connect_error() -> None:
    assert is_retryable_connect_error(ConnectionError(errno.ETIMEDOUT, "timeout"))
    assert not is_retryable_connect_error(ValueError("nope"))
