"""Unit tests for the Antigravity data-driven adapter (no network I/O)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from nanobot.providers import antigravity_adapter as adapter_module
from nanobot.providers.antigravity_adapter import (
    AntigravityAdapter,
    apply_overrides,
    build_adapter,
    build_headers,
    discover_local_client_credentials,
    normalize_model_id,
    render_user_agent,
    resolve_user_agent_version,
)

# Synthetic samples assembled at runtime so no credential-shaped literal is
# committed (secret scanners flag the raw patterns). Secrets carry the fixed
# 28-character body Google issues.
_FAKE_CLIENT_ID = (
    "123456789012-abcdefghij"
    "klmnopqrstuvwxyz012345.apps.googleusercontent.com"
)
_FAKE_SHARED_CLIENT_ID = (
    "1071006060591-fakeclient"
    "body00000000000000.apps.googleusercontent.com"
)
_FAKE_CLIENT_SECRET = "GOCS" + "PX-" + "0123456789abcdefghijklmnopqr"
_FAKE_CLIENT_SECRET_ALT = "GOCS" + "PX-" + "zyxwvutsrqponmlkjihgfedcba98"


@pytest.fixture(autouse=True)
def _clear_credential_cache() -> Iterator[None]:
    discover_local_client_credentials.cache_clear()
    yield
    discover_local_client_credentials.cache_clear()


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


def test_discover_local_client_credentials_prefers_shared_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blob = tmp_path / "agy.bin"
    blob.write_bytes(
        " ".join(
            [
                _FAKE_CLIENT_ID,
                _FAKE_SHARED_CLIENT_ID,
                _FAKE_CLIENT_SECRET,
                _FAKE_CLIENT_SECRET_ALT,
            ]
        ).encode()
    )
    monkeypatch.setattr(adapter_module, "_candidate_client_files", lambda: [blob])

    assert discover_local_client_credentials() == (
        _FAKE_SHARED_CLIENT_ID,
        (_FAKE_CLIENT_SECRET, _FAKE_CLIENT_SECRET_ALT),
    )


def test_discover_local_client_credentials_without_shared_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blob = tmp_path / "gemini.bin"
    blob.write_bytes((_FAKE_CLIENT_ID + " " + _FAKE_CLIENT_SECRET).encode())
    monkeypatch.setattr(adapter_module, "_candidate_client_files", lambda: [blob])

    assert discover_local_client_credentials() == (_FAKE_CLIENT_ID, (_FAKE_CLIENT_SECRET,))


def test_discover_local_client_credentials_requires_both(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blob = tmp_path / "agy.bin"
    blob.write_bytes(_FAKE_CLIENT_ID.encode())
    monkeypatch.setattr(adapter_module, "_candidate_client_files", lambda: [blob])

    assert discover_local_client_credentials() is None


def test_build_adapter_falls_back_to_discovered_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blob = tmp_path / "agy.bin"
    blob.write_bytes(
        (
            _FAKE_SHARED_CLIENT_ID + " " + _FAKE_CLIENT_SECRET + " " + _FAKE_CLIENT_SECRET_ALT
        ).encode()
    )
    monkeypatch.setattr(adapter_module, "_candidate_client_files", lambda: [blob])
    monkeypatch.delenv("NANOBOT_ANTIGRAVITY_CLIENT_ID", raising=False)
    monkeypatch.delenv("NANOBOT_ANTIGRAVITY_CLIENT_SECRET", raising=False)

    class _Settings:
        pass

    adapter = build_adapter(_Settings())

    assert adapter.client_id == _FAKE_SHARED_CLIENT_ID
    assert adapter.client_secret == _FAKE_CLIENT_SECRET
    assert adapter.client_secret_candidates == (_FAKE_CLIENT_SECRET_ALT,)
