"""Tests for Google Antigravity OAuth (PKCE, form encoding, storage, catalog)."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

import nanobot.providers.antigravity_oauth as oauth
from nanobot.providers.antigravity_adapter import AntigravityAdapter
from nanobot.providers.antigravity_oauth import (
    REFRESH_LEAD_MS,
    AntigravityOAuthError,
    AntigravityOAuthReauthRequiredError,
    AntigravityToken,
    _parse_antigravity_models,
    _token_from_response,
    exchange_code_for_tokens,
    generate_pkce,
    is_permanent_grant_failure,
    next_backoff_ms,
    next_refresh_delay_ms,
    refresh_antigravity_token,
    token_is_fresh,
)


@pytest.fixture(autouse=True)
def _oauth_client_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Antigravity ships no OAuth client; tests supply a dummy one via env."""

    monkeypatch.setenv("NANOBOT_ANTIGRAVITY_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("NANOBOT_ANTIGRAVITY_CLIENT_SECRET", "test-client-secret")


def test_generate_pkce_challenge_is_s256_of_verifier() -> None:
    verifier, challenge = generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert challenge == expected.rstrip(b"=").decode()
    assert "=" not in verifier and "=" not in challenge


def test_token_is_fresh() -> None:
    fresh = AntigravityToken(access="a", refresh="r", expires=oauth._now_ms() + 60_000)
    stale = AntigravityToken(access="a", refresh="r", expires=oauth._now_ms() - 1)
    assert token_is_fresh(fresh)
    assert not token_is_fresh(stale)
    assert not token_is_fresh(fresh, min_ttl_ms=120_000)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (400, "invalid_grant", True),
        (401, "invalid_token", True),
        (400, "token has been expired or revoked", True),
        (400, "something weird", False),
        (429, "slow down", False),
        (503, "unavailable", False),
    ],
)
def test_is_permanent_grant_failure(status: int, body: str, expected: bool) -> None:
    assert is_permanent_grant_failure(status, body) is expected


def test_next_backoff_sequence_and_cap() -> None:
    assert next_backoff_ms(0) == 5 * 60 * 1000
    assert next_backoff_ms(4) == 60 * 60 * 1000
    assert next_backoff_ms(99) == 60 * 60 * 1000


def test_next_refresh_delay_is_relative_to_lead() -> None:
    now = 1_000_000
    token = AntigravityToken(access="a", refresh="r", expires=now + REFRESH_LEAD_MS + 5000)
    assert next_refresh_delay_ms(token, now=now) == 5000
    assert next_refresh_delay_ms(AntigravityToken(access="a", refresh="r", expires=now), now=now) == 0


def test_token_from_response_keeps_identity_fields() -> None:
    token = _token_from_response(
        {"access_token": "a", "refresh_token": "r2", "expires_in": 3600},
        adapter=AntigravityAdapter(),
        project_id="proj-1",
        email="me@example.com",
    )
    assert token.refresh == "r2"
    assert token.project_id == "proj-1"
    assert token.email == "me@example.com"
    assert token.expires <= oauth._now_ms() + 3600 * 1000 - oauth.EXPIRY_MARGIN_MS + 100
    kept = _token_from_response(
        {"access_token": "a", "expires_in": 10}, adapter=AntigravityAdapter(), previous_refresh="old"
    )
    assert kept.refresh == "old"


def test_exchange_code_uses_form_encoding() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = parse_qs(request.content.decode())
        captured["content_type"] = request.headers.get("content-type")
        return httpx.Response(
            200, json={"access_token": "acc", "refresh_token": "ref", "expires_in": 60}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        token = exchange_code_for_tokens(
            "code", "verifier", "http://localhost:51121/oauth-callback", client=client
        )

    assert token.access == "acc"
    assert captured["content_type"] == "application/x-www-form-urlencoded"
    assert captured["body"]["grant_type"] == ["authorization_code"]
    assert captured["body"]["code_verifier"] == ["verifier"]
    assert captured["body"]["code"] == ["code"]


def test_refresh_classifies_permanent_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AntigravityOAuthReauthRequiredError):
            refresh_antigravity_token("dead", client=client)


def test_refresh_transient_failure_raises_generic_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AntigravityOAuthError):
            refresh_antigravity_token("live", client=client)


def test_storage_round_trip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    storage = tmp_path / "antigravity.json"
    monkeypatch.setattr(oauth, "get_antigravity_oauth_storage_path", lambda: storage)

    token = AntigravityToken(
        access="a", refresh="r", expires=123, project_id="p", email="e@x"
    )
    oauth.write_antigravity_token(token)
    assert oauth.load_antigravity_token() == token
    assert oauth.get_antigravity_oauth_login_status() == token
    assert oauth.logout_antigravity_oauth() is True
    assert oauth.load_antigravity_token() is None


def test_get_token_returns_fresh_without_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage = tmp_path / "antigravity.json"
    monkeypatch.setattr(oauth, "get_antigravity_oauth_storage_path", lambda: storage)
    oauth.write_antigravity_token(
        AntigravityToken(
            access="a", refresh="r", expires=oauth._now_ms() + 60 * 60 * 1000, project_id="p"
        )
    )

    def boom(*_args: object, **_kwargs: object) -> AntigravityToken:
        raise AssertionError("should not refresh a fresh token")

    monkeypatch.setattr(oauth, "refresh_antigravity_token", boom)
    monkeypatch.setattr(oauth, "discover_project", lambda *a, **k: "should-not-run")
    assert oauth.get_antigravity_oauth_token().access == "a"


def test_get_token_refreshes_and_preserves_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage = tmp_path / "antigravity.json"
    monkeypatch.setattr(oauth, "get_antigravity_oauth_storage_path", lambda: storage)
    oauth.write_antigravity_token(
        AntigravityToken(access="old", refresh="r1", expires=0, project_id="proj")
    )

    def fake_refresh(refresh_token: str, **_kwargs: object) -> AntigravityToken:
        assert refresh_token == "r1"
        return AntigravityToken(access="new", refresh="r2", expires=oauth._now_ms() + 3_600_000)

    monkeypatch.setattr(oauth, "refresh_antigravity_token", fake_refresh)
    token = oauth.get_antigravity_oauth_token()
    assert token.access == "new"
    assert token.project_id == "proj"
    assert oauth.load_antigravity_token() == token


def test_get_token_requires_login(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        oauth, "get_antigravity_oauth_storage_path", lambda: tmp_path / "missing.json"
    )
    with pytest.raises(AntigravityOAuthReauthRequiredError):
        oauth.get_antigravity_oauth_token()


def test_login_flow_completes_with_pasted_callback_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage = tmp_path / "antigravity.json"
    monkeypatch.setattr(oauth, "get_antigravity_oauth_storage_path", lambda: storage)
    expected = AntigravityToken(
        access="acc", refresh="ref", expires=oauth._now_ms() + 100_000, project_id="proj"
    )
    monkeypatch.setattr(oauth, "exchange_code_for_tokens", lambda *a, **k: expected)
    monkeypatch.setattr(oauth, "get_user_email", lambda *a, **k: "me@example.com")
    monkeypatch.setattr(oauth, "discover_project", lambda *a, **k: "proj")

    flow = oauth.start_antigravity_oauth_login(
        adapter=AntigravityAdapter(callback_port=0), timeout_s=30
    )
    try:
        result = flow.complete(
            f"http://localhost:1/oauth-callback?code=abc&state={flow._state}"  # noqa: SLF001
        )
        assert result is not None
        assert result.access == "acc"
        assert result.project_id == "proj"
        assert result.email == "me@example.com"
        assert oauth.load_antigravity_token() == result
    finally:
        flow.cancel()


def test_login_flow_rejects_state_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        oauth, "get_antigravity_oauth_storage_path", lambda: tmp_path / "antigravity.json"
    )
    flow = oauth.start_antigravity_oauth_login(
        adapter=AntigravityAdapter(callback_port=0), timeout_s=30
    )
    try:
        with pytest.raises(AntigravityOAuthError):
            flow.complete("http://localhost:1/oauth-callback?code=abc&state=wrong")
    finally:
        flow.cancel()


def test_login_flow_pending_returns_none() -> None:
    flow = oauth.start_antigravity_oauth_login(
        adapter=AntigravityAdapter(callback_port=0), timeout_s=30
    )
    try:
        assert flow.complete() is None
    finally:
        flow.cancel()


def test_login_flow_redirect_and_authorize_url() -> None:
    flow = oauth.start_antigravity_oauth_login(
        adapter=AntigravityAdapter(callback_port=0), timeout_s=30
    )
    try:
        assert flow.redirect_uri.startswith("http://localhost:")
        assert flow.redirect_uri.endswith("/oauth-callback")
        assert "code_challenge_method=S256" in flow.authorization_url
        assert "access_type=offline" in flow.authorization_url
        assert "accounts.google.com" in flow.authorization_url
    finally:
        flow.cancel()


async def test_proactive_refresher_refreshes_when_due(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import asyncio

    storage = tmp_path / "antigravity.json"
    monkeypatch.setattr(oauth, "get_antigravity_oauth_storage_path", lambda: storage)
    oauth.write_antigravity_token(
        AntigravityToken(access="old", refresh="r1", expires=oauth._now_ms() - 1)
    )

    def fake_get(**_kwargs: object) -> AntigravityToken:
        token = AntigravityToken(access="new", refresh="r2", expires=oauth._now_ms() + 3_600_000)
        oauth.write_antigravity_token(token)
        return token

    monkeypatch.setattr(oauth, "get_antigravity_oauth_token", fake_get)
    refreshed: list[AntigravityToken] = []
    refresher = oauth.ProactiveRefresher(on_refreshed=refreshed.append)
    refresher.start()
    try:
        await asyncio.sleep(0.1)
    finally:
        await refresher.stop()
    assert refreshed and refreshed[0].access == "new"


async def test_start_proactive_refresher_starts_even_without_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        oauth, "get_antigravity_oauth_storage_path", lambda: tmp_path / "missing.json"
    )
    refresher = oauth.start_proactive_refresher()
    try:
        assert refresher.is_running
    finally:
        await refresher.stop()


def test_parse_antigravity_models_keeps_named_models() -> None:
    payload = {
        "models": {
            "gemini-3.7-flash-tiered": {"displayName": "Gemini 3.7 Flash"},
            "gemini-3-pro-low": {"displayName": "Gemini 3 Pro (Low)"},
            "claude-opus-4-6-thinking": {"displayName": "Claude Opus 4.6 Thinking"},
            "tab_flash_lite_preview": {"displayName": ""},
            # 3.6 tiered is nameless BUT has named per-tier siblings -> hidden.
            "gemini-3.6-flash-low": {"displayName": "Gemini 3.6 Flash (Low)"},
            "gemini-3.6-flash-medium": {"displayName": "Gemini 3.6 Flash (Medium)"},
            "gemini-3.6-flash-tiered": {},
        }
    }
    models = _parse_antigravity_models(payload)
    ids = {m.id for m in models}
    assert "google-antigravity/gemini-3.7-flash-tiered" in ids
    assert "google-antigravity/gemini-3.6-flash-medium" in ids
    assert "google-antigravity/claude-opus-4-6-thinking" in ids
    assert all("tab_flash_lite_preview" not in m.id for m in models)
    assert all("gemini-3.6-flash-tiered" not in m.id for m in models)


def test_parse_antigravity_models_synthesizes_nameless_tiered() -> None:
    payload = {
        "models": {
            "gemini-3.8-flash-tiered": {},  # nameless, no siblings -> surfaced
            "gemini-3.6-flash-tiered": {},  # also no siblings in this payload
        }
    }
    models = _parse_antigravity_models(payload)
    by_id = {m.id: m for m in models}
    assert by_id["google-antigravity/gemini-3.8-flash-tiered"].label == "Gemini 3.8 Flash"
    assert by_id["google-antigravity/gemini-3.6-flash-tiered"].label == "Gemini 3.6 Flash"


def test_parse_antigravity_models_normalizes_bare_pro() -> None:
    payload = {"models": {"gemini-3.1-pro": {"displayName": "Gemini 3.1 Pro"}}}
    models = _parse_antigravity_models(payload)
    assert {m.id for m in models} == {"google-antigravity/gemini-3.1-pro-low"}


def test_parse_antigravity_models_dedupes_by_display_name() -> None:
    payload = {
        "models": {
            "gemini-3.1-pro-high": {"displayName": "Gemini 3.1 Pro (High)"},
            "gemini-pro-agent": {"displayName": "Gemini 3.1 Pro (High)"},
        }
    }
    models = _parse_antigravity_models(payload)
    # The canonical `-agent` id wins over the stale per-tier alias.
    assert [m.id for m in models] == ["google-antigravity/gemini-pro-agent"]


def test_parse_antigravity_models_rejects_bad_payload() -> None:
    assert _parse_antigravity_models(None) == ()
    assert _parse_antigravity_models({"models": []}) == ()


def _flow_with_server():  # noqa: ANN202 - test helper
    return oauth.start_antigravity_oauth_login(
        adapter=AntigravityAdapter(callback_port=0), timeout_s=30
    )


def test_callback_surfaces_google_error_instead_of_generic_page() -> None:
    flow = _flow_with_server()
    try:
        port = flow._server.server_port  # noqa: SLF001
        response = httpx.get(
            f"http://127.0.0.1:{port}/oauth-callback"
            f"?error=invalid_scope&error_description=Bad+scope&state={flow._state}"  # noqa: SLF001
        )
        assert response.status_code == 200
        assert "invalid_scope" in response.text
        assert "Invalid OAuth callback" not in response.text
        with pytest.raises(AntigravityOAuthError) as excinfo:
            flow.complete()
        assert "Google sign-in failed" in str(excinfo.value)
        assert "invalid_scope" in str(excinfo.value)
    finally:
        flow.cancel()


def test_callback_reports_state_mismatch() -> None:
    flow = _flow_with_server()
    try:
        port = flow._server.server_port  # noqa: SLF001
        response = httpx.get(f"http://127.0.0.1:{port}/oauth-callback?code=abc&state=wrong")
        assert response.status_code == 400
        assert "state mismatch" in response.text.lower()
    finally:
        flow.cancel()


def test_callback_reports_missing_code() -> None:
    flow = _flow_with_server()
    try:
        port = flow._server.server_port  # noqa: SLF001
        response = httpx.get(
            f"http://127.0.0.1:{port}/oauth-callback?state={flow._state}"  # noqa: SLF001
        )
        assert response.status_code == 400
        assert "No authorization code" in response.text
    finally:
        flow.cancel()


def test_parse_authorization_response_surfaces_error() -> None:
    with pytest.raises(AntigravityOAuthError) as excinfo:
        oauth._parse_authorization_response(
            "http://localhost:1/oauth-callback?error=access_denied&error_description=nope", "s"
        )
    assert "access_denied" in str(excinfo.value)
