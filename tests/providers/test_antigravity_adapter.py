"""Unit tests for the Antigravity data-driven adapter (no network I/O)."""

from __future__ import annotations

import pytest

from nanobot.providers.antigravity_adapter import (
    AntigravityAdapter,
    apply_overrides,
    build_adapter,
    build_headers,
    normalize_model_id,
    render_user_agent,
    resolve_user_agent_version,
)


def test_normalize_model_id_applies_routing_suffix() -> None:
    assert normalize_model_id("gemini-3-pro") == "gemini-3-pro-low"
    assert normalize_model_id("gemini-3.1-pro") == "gemini-3.1-pro-low"
    assert normalize_model_id("gemini-3-1-pro") == "gemini-3-1-pro-low"
    assert normalize_model_id("gemini-3.1-pro-high") == "gemini-pro-agent"
    # Already-normalized / unknown ids pass through untouched.
    assert normalize_model_id("gemini-3-pro-low") == "gemini-3-pro-low"
    assert normalize_model_id("claude-opus-4-6-thinking") == "claude-opus-4-6-thinking"


def test_normalize_model_id_honours_custom_aliases() -> None:
    assert normalize_model_id("x", {"x": "y"}) == "y"


def test_resolve_user_agent_version_is_a_floor() -> None:
    assert resolve_user_agent_version(None) == "1.21.9"
    assert resolve_user_agent_version("1.0.0") == "1.21.9"
    assert resolve_user_agent_version("1.22.0") == "1.22.0"
    # A non-numeric custom tag is never silently rewritten.
    assert resolve_user_agent_version("custom-tag") == "custom-tag"


def test_render_user_agent_format() -> None:
    adapter = AntigravityAdapter()
    ua = render_user_agent(adapter, platform_label="windows", arch_label="x64")
    assert ua == "antigravity/1.21.9 windows/x64"


def test_build_headers_sets_identity() -> None:
    headers = build_headers(AntigravityAdapter(), "tok-123", reasoning_claude=False)
    assert headers["Authorization"] == "Bearer tok-123"
    assert headers["Content-Type"] == "application/json"
    assert headers["Accept"] == "text/event-stream"
    assert headers["User-Agent"].startswith("antigravity/")
    assert "PLATFORM_UNSPECIFIED" in headers["Client-Metadata"]
    assert "anthropic-beta" not in headers

    claude = build_headers(AntigravityAdapter(), "tok", reasoning_claude=True)
    assert claude["anthropic-beta"] == "interleaved-thinking-2025-05-14"


def test_build_headers_applies_overrides() -> None:
    adapter = AntigravityAdapter(header_overrides={"X-Goog-Api-Client": "gl-node/22"})
    headers = build_headers(adapter, "tok")
    assert headers["X-Goog-Api-Client"] == "gl-node/22"


def test_apply_overrides_merges_body_and_request() -> None:
    adapter = AntigravityAdapter(
        body_overrides={"requestType": "chat"},
        request_overrides={"sessionId": "s1"},
    )
    wrapper = {"project": "p", "request": {"contents": []}}
    result = apply_overrides(wrapper, adapter)
    assert result["requestType"] == "chat"
    assert result["request"]["sessionId"] == "s1"
    assert result["request"]["contents"] == []
    # Original untouched.
    assert "requestType" not in wrapper


def test_client_credentials_resolved_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOBOT_ANTIGRAVITY_CLIENT_ID", "env-id")
    monkeypatch.setenv("NANOBOT_ANTIGRAVITY_CLIENT_SECRET", "env-secret")

    adapter = AntigravityAdapter()

    assert adapter.client_id == "env-id"
    assert adapter.client_secret == "env-secret"


def test_build_adapter_prefers_config_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOBOT_ANTIGRAVITY_CLIENT_ID", "env-id")
    monkeypatch.setenv("NANOBOT_ANTIGRAVITY_CLIENT_SECRET", "env-secret")

    class _Settings:
        client_id = "cfg-id"
        client_secret = "cfg-secret"

    adapter = build_adapter(_Settings())

    assert adapter.client_id == "cfg-id"
    assert adapter.client_secret == "cfg-secret"
