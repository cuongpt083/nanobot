"""Tests for Anthropic OAuth (PKCE, refresh rotation, classification, storage)."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import nanobot.providers.anthropic_oauth as oauth
from nanobot.providers.anthropic_oauth import (
    REFRESH_LEAD_MS,
    AnthropicOAuthError,
    AnthropicOAuthReauthRequiredError,
    AnthropicToken,
    _token_from_response,
    exchange_code_for_tokens,
    generate_pkce,
    is_permanent_grant_failure,
    next_backoff_ms,
    next_refresh_delay_ms,
    refresh_anthropic_token,
    token_is_fresh,
)


def test_generate_pkce_challenge_is_s256_of_verifier() -> None:
    verifier, challenge = generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert challenge == expected.rstrip(b"=").decode()
    assert "=" not in verifier and "=" not in challenge


def test_token_is_fresh() -> None:
    fresh = AnthropicToken(access="a", refresh="r", expires=oauth._now_ms() + 60_000)
    stale = AnthropicToken(access="a", refresh="r", expires=oauth._now_ms() - 1)
    assert token_is_fresh(fresh)
    assert not token_is_fresh(stale)
    assert not token_is_fresh(fresh, min_ttl_ms=120_000)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (400, "invalid_grant", True),
        (401, "refresh token expired", True),
        (403, "refresh_token_reused", True),
        (400, "something weird", False),
        (429, "slow down", False),
        (503, "unavailable", False),
        (500, "boom", False),
    ],
)
def test_is_permanent_grant_failure(status: int, body: str, expected: bool) -> None:
    assert is_permanent_grant_failure(status, body) is expected


def test_next_backoff_sequence_and_cap() -> None:
    assert next_backoff_ms(0) == 5 * 60 * 1000
    assert next_backoff_ms(1) == 10 * 60 * 1000
    assert next_backoff_ms(2) == 20 * 60 * 1000
    assert next_backoff_ms(3) == 40 * 60 * 1000
    assert next_backoff_ms(4) == 60 * 60 * 1000
    assert next_backoff_ms(99) == 60 * 60 * 1000


def test_next_refresh_delay_is_relative_to_lead() -> None:
    now = 1_000_000
    token = AnthropicToken(access="a", refresh="r", expires=now + REFRESH_LEAD_MS + 5000)
    assert next_refresh_delay_ms(token, now=now) == 5000
    due = AnthropicToken(access="a", refresh="r", expires=now)
    assert next_refresh_delay_ms(due, now=now) == 0


def test_token_from_response_applies_expiry_margin_and_rotates_refresh() -> None:
    token = _token_from_response({"access_token": "a", "refresh_token": "r2", "expires_in": 3600})
    assert token.refresh == "r2"
    assert token.expires <= oauth._now_ms() + 3600 * 1000 - oauth.EXPIRY_MARGIN_MS + 100
    # Missing refresh_token keeps the previous one.
    kept = _token_from_response({"access_token": "a", "expires_in": 10}, previous_refresh="old")
    assert kept.refresh == "old"


def test_exchange_code_uses_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"access_token": "acc", "refresh_token": "ref", "expires_in": 60})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        token = exchange_code_for_tokens("code", "verifier", "http://127.0.0.1/cb", "state", client=client)

    assert token.access == "acc"
    assert captured["body"]["grant_type"] == "authorization_code"
    assert captured["body"]["code_verifier"] == "verifier"


def test_refresh_classifies_permanent_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AnthropicOAuthReauthRequiredError):
            refresh_anthropic_token("dead", client=client)


def test_refresh_transient_failure_raises_generic_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AnthropicOAuthError):
            refresh_anthropic_token("live", client=client)


def test_storage_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = tmp_path / "anthropic.json"
    monkeypatch.setattr(oauth, "get_anthropic_oauth_storage_path", lambda: storage)

    token = AnthropicToken(access="a", refresh="r", expires=123)
    oauth.write_anthropic_token(token)
    assert oauth.load_anthropic_token() == token
    assert oauth.get_anthropic_oauth_login_status() == token
    assert oauth.logout_anthropic_oauth() is True
    assert oauth.load_anthropic_token() is None


def test_get_token_returns_fresh_without_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage = tmp_path / "anthropic.json"
    monkeypatch.setattr(oauth, "get_anthropic_oauth_storage_path", lambda: storage)
    oauth.write_anthropic_token(
        AnthropicToken(access="a", refresh="r", expires=oauth._now_ms() + 60 * 60 * 1000)
    )

    def boom(*_args: object, **_kwargs: object) -> AnthropicToken:
        raise AssertionError("should not refresh a fresh token")

    monkeypatch.setattr(oauth, "refresh_anthropic_token", boom)
    assert oauth.get_anthropic_oauth_token().access == "a"


def test_get_token_refreshes_and_writes_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage = tmp_path / "anthropic.json"
    monkeypatch.setattr(oauth, "get_anthropic_oauth_storage_path", lambda: storage)
    oauth.write_anthropic_token(AnthropicToken(access="old", refresh="r1", expires=0))

    def fake_refresh(refresh_token: str, **_kwargs: object) -> AnthropicToken:
        assert refresh_token == "r1"
        return AnthropicToken(access="new", refresh="r2", expires=oauth._now_ms() + 3600_000)

    monkeypatch.setattr(oauth, "refresh_anthropic_token", fake_refresh)
    token = oauth.get_anthropic_oauth_token()
    assert token.access == "new"
    assert oauth.load_anthropic_token() == token


def test_get_token_requires_login(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        oauth, "get_anthropic_oauth_storage_path", lambda: tmp_path / "missing.json"
    )
    with pytest.raises(AnthropicOAuthReauthRequiredError):
        oauth.get_anthropic_oauth_token()
