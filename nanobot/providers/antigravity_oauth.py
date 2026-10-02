"""Google Antigravity subscription OAuth (Authorization Code + PKCE).

Mirrors the reference ``agy`` / pi-ai flow: Google OAuth2 with the shared Gemini
CLI client, a fixed loopback callback (port 51121), form-encoded token
exchange/refresh, a discovered Cloud Code Assist ``project`` id, then a
rotation-aware, file-locked credential store with proactive refresh.

.. warning::
   Impersonating the ``agy`` client to use a Google subscription from a
   third-party app may violate Google's terms of service and risks account
   action. Prefer Google AI Studio / Vertex AI API keys. Kept for
   interoperability study on accounts you own; disabled by default. See
   ``docs/plan-google-antigravity-provider.md``.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import html as html_module
import json
import os
import queue
import re
import secrets
import threading
import time
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from filelock import FileLock
from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.providers.antigravity_adapter import (
    CLIENT_ID_ENV_VAR,
    CLIENT_SECRET_ENV_VAR,
    DEFAULT_ENDPOINT,
    DEFAULT_PROJECT_ID,
    AntigravityAdapter,
    build_headers,
)
from nanobot.providers.oauth_model_catalog import (
    OAuthCatalogAuthRequiredError,
    OAuthModelCatalog,
    OAuthModelCatalogSnapshot,
)
from nanobot.providers.registry import ProviderModelSpec
from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]

#: Refresh this long before the stored expiry so the refresh token never lapses
#: while the app is idle.
REFRESH_LEAD_MS = 10 * 60 * 1000
#: Safety margin subtracted from ``expires_in`` when persisting (google refresh
#: tokens are long-lived; matunty margin guards clock skew).
EXPIRY_MARGIN_MS = 5 * 60 * 1000
_DEFAULT_TOKEN_TTL_S = 60 * 60
_HTTP_TIMEOUT_S = 15.0
_PROACTIVE_BACKOFF_MS = (5, 10, 20, 40, 60)
_PROACTIVE_MAX_BACKOFF_MS = 60 * 60 * 1000
_CALLBACK_PATH = "/oauth-callback"

#: Local agy caches that hold an already-registered Cloud Code Assist project id.
_AGY_PROJECT_SOURCES: tuple[str, ...] = (
    "~/.gemini/antigravity-cli/cache/default_project_id.txt",
    "~/.antigravitycli",
    "~/.gemini/config/projects",
)


class AntigravityOAuthError(RuntimeError):
    """An actionable Antigravity OAuth failure with no credential material."""


class AntigravityOAuthReauthRequiredError(AntigravityOAuthError):
    """No usable login remains; an explicit sign-in is required."""


def _require_client_credentials(adapter: AntigravityAdapter) -> None:
    """Fail fast with an actionable message when the OAuth client is unset."""

    if adapter.client_id and adapter.client_secret:
        return
    raise AntigravityOAuthError(
        "Google Antigravity OAuth client credentials are not configured. "
        f"Set {CLIENT_ID_ENV_VAR} and {CLIENT_SECRET_ENV_VAR}, configure "
        "provider.antigravity.client_id / client_secret, or install the Gemini "
        "CLI / Antigravity CLI so they can be detected automatically."
    )


def _client_secret_candidates(adapter: AntigravityAdapter) -> tuple[str, ...]:
    """Primary secret first, then any discovered alternatives (dedup, non-empty)."""

    ordered = [adapter.client_secret, *adapter.client_secret_candidates]
    return tuple(dict.fromkeys(secret for secret in ordered if secret))


def _is_invalid_client(response: httpx.Response) -> bool:
    """True when Google rejected the OAuth client credentials (wrong secret)."""

    if response.status_code != 401:
        return False
    try:
        payload = response.json()
    except ValueError:
        return True
    if not isinstance(payload, dict):
        return False
    return cast(dict[str, Any], payload).get("error") == "invalid_client"


@dataclass(frozen=True)
class AntigravityToken:
    """Persisted Antigravity OAuth token material."""

    access: str
    refresh: str | None
    expires: int
    project_id: str | None = None
    email: str | None = None

    @classmethod
    def from_dict(cls, value: Any) -> AntigravityToken | None:
        if not isinstance(value, dict):
            return None
        data = cast(dict[str, Any], value)
        access = data.get("access")
        refresh = data.get("refresh")
        expires = data.get("expires")
        project_id = data.get("project_id")
        email = data.get("email")
        if not isinstance(access, str) or not access:
            return None
        if not isinstance(expires, int):
            return None
        return cls(
            access=access,
            refresh=refresh if isinstance(refresh, str) and refresh else None,
            expires=expires,
            project_id=project_id if isinstance(project_id, str) and project_id else None,
            email=email if isinstance(email, str) and email else None,
        )


# ── Pure helpers ──


def _now_ms() -> int:
    return int(time.time() * 1000)


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def generate_pkce() -> tuple[str, str]:
    """Return a ``(verifier, challenge)`` pair using S256 (RFC 7636)."""

    verifier = _base64url(secrets.token_bytes(32))
    challenge = _base64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def token_is_fresh(token: AntigravityToken, *, min_ttl_ms: int = 0) -> bool:
    """True when the access token outlives ``min_ttl_ms`` from now."""

    return bool(token.access) and token.expires > _now_ms() + max(0, min_ttl_ms)


def is_permanent_grant_failure(status_code: int, body: str) -> bool:
    """Classify a token-endpoint failure as permanent (needs re-login)."""

    if status_code == 429 or status_code >= 500:
        return False
    if status_code not in (400, 401, 403):
        return False
    lowered = body.lower()
    markers = (
        "invalid_grant",
        "invalid_token",
        "refresh token expired",
        "refresh_token_expired",
        "refresh token not found",
        "refresh_token_reused",
        "refresh token reused",
        "token has been expired or revoked",
    )
    return any(marker in lowered for marker in markers)


def next_backoff_ms(attempt: int) -> int:
    """Exponential backoff 5→10→20→40→60 minutes, then hold at 60."""

    if attempt < 0:
        attempt = 0
    if attempt >= len(_PROACTIVE_BACKOFF_MS):
        return _PROACTIVE_MAX_BACKOFF_MS
    return _PROACTIVE_BACKOFF_MS[attempt] * 60 * 1000


def next_refresh_delay_ms(
    token: AntigravityToken, *, now: int | None = None, lead_ms: int = REFRESH_LEAD_MS
) -> int:
    """Milliseconds until proactive refresh should fire (never negative)."""

    reference = _now_ms() if now is None else now
    return max(0, token.expires - lead_ms - reference)


# ── Storage ──


def get_antigravity_oauth_storage_path() -> Path:
    """Return the instance-scoped Antigravity OAuth credential path."""

    return get_data_dir() / "auth" / "antigravity.json"


def _token_lock() -> FileLock:
    path = get_antigravity_oauth_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path.with_suffix(".lock")), timeout=120)


def load_antigravity_token() -> AntigravityToken | None:
    path = get_antigravity_oauth_storage_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not read Antigravity OAuth credentials: {}", type(exc).__name__)
        return None
    return AntigravityToken.from_dict(payload)


def write_antigravity_token(token: AntigravityToken) -> None:
    path = get_antigravity_oauth_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(path.parent, 0o700)
    _write_text_atomic(path, json.dumps(asdict(token), indent=2, ensure_ascii=False))
    with suppress(OSError):
        os.chmod(path, 0o600)


def logout_antigravity_oauth() -> bool:
    path = get_antigravity_oauth_storage_path()
    with _token_lock():
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True


def get_antigravity_oauth_login_status() -> AntigravityToken | None:
    return load_antigravity_token()


# ── Status listeners ──

AntigravityOAuthStatus = Literal["refreshed", "reauth_required"]
AntigravityOAuthStatusListener = Callable[
    [AntigravityOAuthStatus, "AntigravityToken | None"], None
]

_status_listeners: list[AntigravityOAuthStatusListener] = []
_status_listeners_lock = threading.Lock()
_last_reauth_key: str | None = None


def add_antigravity_oauth_status_listener(
    listener: AntigravityOAuthStatusListener,
) -> Callable[[], None]:
    """Register ``listener(status, token)``; returns an unsubscribe callable."""

    with _status_listeners_lock:
        _status_listeners.append(listener)

    def _remove() -> None:
        with _status_listeners_lock, suppress(ValueError):
            _status_listeners.remove(listener)

    return _remove


def _emit_oauth_status(status: AntigravityOAuthStatus, token: AntigravityToken | None) -> None:
    global _last_reauth_key
    dedup = (token.refresh if token is not None and token.refresh else None) or "__no_refresh__"
    with _status_listeners_lock:
        if status == "reauth_required":
            if dedup == _last_reauth_key:
                return
            _last_reauth_key = dedup
        else:
            _last_reauth_key = None
        listeners = list(_status_listeners)
    for listener in listeners:
        try:
            listener(status, token)
        except Exception as exc:  # noqa: BLE001 — a listener must never break the token path
            logger.warning("Antigravity OAuth status listener failed: {}", type(exc).__name__)


# ── Token endpoint ──


def _http_client(proxy: str | None) -> httpx.Client:
    kwargs: dict[str, Any] = {"timeout": _HTTP_TIMEOUT_S}
    if proxy:
        kwargs.update(proxy=proxy, trust_env=False)
    return httpx.Client(**kwargs)


def _token_from_response(
    payload: dict[str, Any],
    *,
    adapter: AntigravityAdapter,
    previous_refresh: str | None = None,
    project_id: str | None = None,
    email: str | None = None,
) -> AntigravityToken:
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise AntigravityOAuthError("Antigravity sign-in returned no access token.")
    try:
        expires_in = max(1, int(payload.get("expires_in") or _DEFAULT_TOKEN_TTL_S))
    except (TypeError, ValueError):
        expires_in = _DEFAULT_TOKEN_TTL_S
    refresh = payload.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        refresh = previous_refresh
    return AntigravityToken(
        access=access,
        refresh=refresh,
        expires=_now_ms() + expires_in * 1000 - EXPIRY_MARGIN_MS,
        project_id=project_id or adapter.project_id,
        email=email,
    )


def exchange_code_for_tokens(
    code: str,
    verifier: str,
    redirect_uri: str,
    *,
    adapter: AntigravityAdapter | None = None,
    proxy: str | None = None,
    client: httpx.Client | None = None,
) -> AntigravityToken:
    """Exchange an authorization code (Google expects form encoding)."""

    adapter = adapter or AntigravityAdapter()
    _require_client_credentials(adapter)
    owns_client = client is None
    http_client = client or _http_client(proxy)
    try:
        response: httpx.Response | None = None
        for secret in _client_secret_candidates(adapter):
            response = http_client.post(
                adapter.token_url,
                data={
                    "client_id": adapter.client_id,
                    "client_secret": secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if not _is_invalid_client(response):
                break
    finally:
        if owns_client:
            http_client.close()
    if response is None:
        raise AntigravityOAuthError(
            "Antigravity token exchange could not authenticate the OAuth client."
        )
    if response.status_code >= 400:
        raise AntigravityOAuthError(
            f"Antigravity token exchange failed (HTTP {response.status_code})."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AntigravityOAuthError("Antigravity sign-in returned an invalid token response.") from exc
    if not isinstance(payload, dict):
        raise AntigravityOAuthError("Antigravity sign-in returned no access token.")
    return _token_from_response(cast(dict[str, Any], payload), adapter=adapter)


def refresh_antigravity_token(
    refresh_token: str,
    *,
    adapter: AntigravityAdapter | None = None,
    proxy: str | None = None,
    client: httpx.Client | None = None,
) -> AntigravityToken:
    """Refresh a Google OAuth grant (form-encoded; refresh token may not rotate)."""

    adapter = adapter or AntigravityAdapter()
    _require_client_credentials(adapter)
    owns_client = client is None
    http_client = client or _http_client(proxy)
    try:
        response: httpx.Response | None = None
        for secret in _client_secret_candidates(adapter):
            response = http_client.post(
                adapter.token_url,
                data={
                    "client_id": adapter.client_id,
                    "client_secret": secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if not _is_invalid_client(response):
                break
    finally:
        if owns_client:
            http_client.close()
    if response is None:
        raise AntigravityOAuthError(
            "Antigravity refresh could not authenticate the OAuth client."
        )
    if response.status_code >= 400:
        body_text = response.text
        if is_permanent_grant_failure(response.status_code, body_text):
            raise AntigravityOAuthReauthRequiredError(
                "The Google Antigravity login has expired. Please sign in again."
            )
        raise AntigravityOAuthError(
            f"Antigravity token refresh failed (HTTP {response.status_code})."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AntigravityOAuthError("Antigravity refresh returned an invalid token response.") from exc
    if not isinstance(payload, dict):
        raise AntigravityOAuthError("Antigravity refresh returned no access token.")
    return _token_from_response(
        cast(dict[str, Any], payload),
        adapter=adapter,
        previous_refresh=refresh_token,
    )


# ── Project discovery ──


def _borrow_agy_project_id() -> str | None:
    """Read a registered project id from a local ``agy`` install, if present."""

    for raw in _AGY_PROJECT_SOURCES:
        path = Path(raw).expanduser()
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
            elif path.is_dir():
                for candidate in sorted(path.glob("*.json")):
                    try:
                        data = json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if isinstance(data, dict):
                        mapping = cast(dict[str, Any], data)
                        for key in ("id", "projectId", "project_id"):
                            value = mapping.get(key)
                            if isinstance(value, str) and value.strip():
                                return value.strip()
                    if candidate.stem:
                        return candidate.stem
        except OSError:
            continue
    return None


def discover_project(
    access_token: str,
    *,
    adapter: AntigravityAdapter | None = None,
    proxy: str | None = None,
    client: httpx.Client | None = None,
) -> str:
    """Resolve the Cloud Code Assist project id for this account.

    Order: ``loadCodeAssist`` response → local ``agy`` cache → configured value →
    shipped fallback. (``loadCodeAssist`` may auto-provision on consumer accounts.)
    """

    adapter = adapter or AntigravityAdapter()
    owns_client = client is None
    http_client = client or _http_client(proxy)
    try:
        for endpoint in adapter.target_endpoints:
            # The daily host is required for the Antigravity tier; the plain host
            # is kept as a last resort only.
            url = f"{endpoint}/v1internal:loadCodeAssist"
            try:
                response = http_client.post(
                    url,
                    json={"metadata": _client_metadata_dict()},
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                        "User-Agent": _load_code_assist_user_agent(adapter),
                        "Client-Metadata": json.dumps(
                            _client_metadata_dict(), separators=(",", ":")
                        ),
                    },
                )
            except httpx.HTTPError:
                continue
            if response.status_code >= 400:
                continue
            try:
                data = response.json()
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            project = cast(dict[str, Any], data).get("cloudaicompanionProject")
            if isinstance(project, str) and project:
                return project
            if isinstance(project, dict):
                inner = cast(dict[str, Any], project).get("id")
                if isinstance(inner, str) and inner:
                    return inner
    finally:
        if owns_client:
            http_client.close()

    borrowed = _borrow_agy_project_id()
    if borrowed:
        return borrowed
    return adapter.project_id or DEFAULT_PROJECT_ID


def _client_metadata_dict() -> dict[str, str]:
    return {
        "ideType": "IDE_UNSPECIFIED",
        "platform": "PLATFORM_UNSPECIFIED",
        "pluginType": "GEMINI",
    }


def _load_code_assist_user_agent(_adapter: AntigravityAdapter) -> str:
    # pi-ai uses the generic Google API UA for the assist call, not the agy UA.
    return "google-api-nodejs-client/9.15.1"


def get_user_email(
    access_token: str,
    *,
    adapter: AntigravityAdapter | None = None,
    proxy: str | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    adapter = adapter or AntigravityAdapter()
    owns_client = client is None
    http_client = client or _http_client(proxy)
    try:
        response = http_client.get(
            adapter.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
        )
        if response.status_code >= 400:
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if owns_client:
            http_client.close()
    if isinstance(payload, dict):
        email = cast(dict[str, Any], payload).get("email")
        if isinstance(email, str) and email:
            return email
    return None


def get_antigravity_oauth_token(
    *,
    adapter: AntigravityAdapter | None = None,
    proxy: str | None = None,
    min_ttl_ms: int = REFRESH_LEAD_MS,
    force_refresh: bool = False,
) -> AntigravityToken:
    """Load a usable token, refreshing (and ensuring a project id) as needed."""

    adapter = adapter or AntigravityAdapter()
    token = load_antigravity_token()
    if token is None:
        raise AntigravityOAuthReauthRequiredError(
            "Google Antigravity is not signed in. "
            "Run `nanobot provider login google-antigravity` first."
        )
    if not force_refresh and token_is_fresh(token, min_ttl_ms=min_ttl_ms):
        token = _ensure_project_id(token, adapter, proxy)
        return token
    if not token.refresh:
        if not force_refresh and token_is_fresh(token):
            return token
        _emit_oauth_status("reauth_required", token)
        raise AntigravityOAuthReauthRequiredError(
            "The Google Antigravity login has expired and cannot be refreshed. Sign in again."
        )

    with _token_lock():
        latest = load_antigravity_token()
        if latest is None:
            _emit_oauth_status("reauth_required", token)
            raise AntigravityOAuthReauthRequiredError("Antigravity credentials disappeared.")
        if not force_refresh and token_is_fresh(latest, min_ttl_ms=min_ttl_ms):
            return _ensure_project_id(latest, adapter, proxy)
        if not latest.refresh:
            return _ensure_project_id(latest, adapter, proxy)
        try:
            refreshed = refresh_antigravity_token(latest.refresh, adapter=adapter, proxy=proxy)
        except AntigravityOAuthReauthRequiredError:
            _emit_oauth_status("reauth_required", latest)
            raise
        # Preserve identity fields Google does not echo back on refresh.
        refreshed = AntigravityToken(
            access=refreshed.access,
            refresh=refreshed.refresh,
            expires=refreshed.expires,
            project_id=latest.project_id or refreshed.project_id,
            email=latest.email or refreshed.email,
        )
        write_antigravity_token(refreshed)
        _emit_oauth_status("refreshed", refreshed)
        logger.info("Antigravity OAuth token refreshed")
        return refreshed


def _ensure_project_id(
    token: AntigravityToken, adapter: AntigravityAdapter, proxy: str | None
) -> AntigravityToken:
    """Best-effort project-id backfill for a token stored without one."""

    if token.project_id:
        return token
    try:
        project_id = discover_project(token.access, adapter=adapter, proxy=proxy)
    except Exception as exc:  # noqa: BLE001 — never block chat on discovery
        logger.warning("Antigravity project discovery failed: {}", type(exc).__name__)
        return token
    updated = AntigravityToken(
        access=token.access,
        refresh=token.refresh,
        expires=token.expires,
        project_id=project_id,
        email=token.email,
    )
    with suppress(Exception):
        write_antigravity_token(updated)
    return updated


# ── Browser login flow ──


def _build_authorize_url(adapter: AntigravityAdapter, redirect_uri: str, challenge: str, state: str) -> str:
    params = {
        "client_id": adapter.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(adapter.scopes),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{adapter.authorize_url}?{urlencode(params)}"


@dataclass
class _CallbackResult:
    code: str
    state: str
    error: str | None = None
    error_description: str | None = None

    @property
    def failure_message(self) -> str | None:
        """Human-readable reason when Google refused the authorization."""

        if not self.error:
            return None
        detail = self.error_description or ""
        return f"Google sign-in failed: {self.error}{f' ({detail})' if detail else ''}"


def _make_callback_server(
    state: str, result_queue: "queue.Queue[_CallbackResult]", port: int
) -> ThreadingHTTPServer:
    class _Handler(BaseHTTPRequestHandler):
        def _respond(self, status: HTTPStatus, body: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
            parsed = urlsplit(self.path)
            if parsed.path != _CALLBACK_PATH:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            params = parse_qs(parsed.query)
            received_state = (params.get("state") or [""])[0]
            code = (params.get("code") or [""])[0]
            error = (params.get("error") or [""])[0]
            error_description = (params.get("error_description") or [""])[0]
            logger.info(
                "Antigravity OAuth callback: state_match={} has_code={} error={}",
                received_state == state,
                bool(code),
                error or "-",
            )

            # Google refused the request (invalid_scope, access_denied, …) and
            # redirected back with an `error` instead of a `code`. Surface it
            # instead of the misleading generic "Invalid OAuth callback." page.
            if error:
                result_queue.put(
                    _CallbackResult(
                        code="",
                        state=received_state,
                        error=error,
                        error_description=error_description,
                    )
                )
                detail = html_module.escape(error_description)
                self._respond(
                    HTTPStatus.OK,
                    f"<h2>Google sign-in failed.</h2><p><b>{html_module.escape(error)}</b>"
                    + (f"<br>{detail}" if detail else "")
                    + "</p><p>You can close this tab and try again.</p>",
                )
                return

            if received_state != state:
                self._respond(
                    HTTPStatus.BAD_REQUEST,
                    "<h2>OAuth state mismatch.</h2>"
                    "<p>The sign-in link is stale or was opened from another tab. "
                    "Start the sign-in again.</p>",
                )
                return

            if not code:
                self._respond(
                    HTTPStatus.BAD_REQUEST,
                    "<h2>No authorization code.</h2>"
                    "<p>Google did not return a code. Start the sign-in again.</p>",
                )
                return

            result_queue.put(_CallbackResult(code=code, state=received_state))
            self._respond(
                HTTPStatus.OK,
                "<h2>Google sign-in complete.</h2>You can close this tab.",
            )

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    except OSError as exc:
        raise AntigravityOAuthError(
            f"Cannot bind 127.0.0.1:{port} for the Antigravity sign-in callback "
            "(port already in use). Close the other process or set a different "
            "providers.google_antigravity.antigravity.callbackPort."
        ) from exc
    server.daemon_threads = True
    return server


def _parse_authorization_response(value: str, expected_state: str) -> str:
    """Accept either a bare authorization code or a full callback URL."""

    raw = value.strip()
    if not raw:
        raise AntigravityOAuthError("No authorization code was provided.")
    if "code=" in raw or "error=" in raw:
        params = parse_qs(urlsplit(raw).query)
        error = (params.get("error") or [""])[0]
        if error:
            detail = (params.get("error_description") or [""])[0]
            raise AntigravityOAuthError(
                f"Google sign-in failed: {error}{f' ({detail})' if detail else ''}"
            )
        received_state = (params.get("state") or [""])[0]
        if expected_state and received_state and received_state != expected_state:
            raise AntigravityOAuthError("OAuth state mismatch. Start the sign-in again.")
        code = (params.get("code") or [""])[0]
        if not code:
            raise AntigravityOAuthError("No authorization code found in the callback URL.")
        return code
    return raw


class AntigravityOAuthLoginFlow:
    """Pending Antigravity login that can finish via loopback or a pasted code."""

    def __init__(
        self,
        *,
        authorization_url: str,
        redirect_uri: str,
        verifier: str,
        state: str,
        adapter: AntigravityAdapter,
        proxy: str | None,
        result_queue: "queue.Queue[_CallbackResult]",
        server: ThreadingHTTPServer,
        timeout_s: float,
    ) -> None:
        self.authorization_url = authorization_url
        self.redirect_uri = redirect_uri
        self._verifier = verifier
        self._state = state
        self._adapter = adapter
        self._proxy = proxy
        self._result_queue = result_queue
        self._server = server
        self._expires_at = time.monotonic() + timeout_s
        self._lock = threading.Lock()
        self._token: AntigravityToken | None = None
        self._error: Exception | None = None
        self._closed = False
        self._server_thread = threading.Thread(
            target=server.serve_forever,
            name="nanobot-antigravity-oauth-callback",
            daemon=True,
        )
        self._server_thread.start()
        self._timeout_timer = threading.Timer(timeout_s, self._expire)
        self._timeout_timer.daemon = True
        self._timeout_timer.start()

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self._expires_at

    @property
    def remaining_seconds(self) -> int:
        return max(0, int(self._expires_at - time.monotonic()))

    def complete(self, authorization_response: str | None = None) -> AntigravityToken | None:
        """Complete this flow, or return ``None`` while the loopback is pending."""

        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()

        if authorization_response is not None:
            code = _parse_authorization_response(authorization_response, self._state)
            return self._finish(_CallbackResult(code=code, state=self._state))
        try:
            callback = self._result_queue.get_nowait()
        except queue.Empty:
            return None
        return self._finish(callback)

    def wait(self, timeout_s: float) -> AntigravityToken:
        """Wait for the loopback callback and complete this flow."""

        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()
        try:
            callback = self._result_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            with self._lock:
                if self._error is not None:
                    raise self._error
            raise AntigravityOAuthError("Timed out waiting for Google sign-in.") from exc
        return self._finish(callback)

    def cancel(self) -> None:
        """Stop the callback listener for an abandoned flow."""

        with self._lock:
            if self._token is None and self._error is None:
                self._error = AntigravityOAuthError("Google sign-in was cancelled.")
            self._close_locked()

    def _finish(self, callback: _CallbackResult) -> AntigravityToken:
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()
            self._close_locked()
            try:
                if callback.error:
                    raise AntigravityOAuthError(
                        callback.failure_message or "Google sign-in failed."
                    )
                if callback.state and callback.state != self._state:
                    raise AntigravityOAuthError("OAuth state mismatch. Start the sign-in again.")
                token = exchange_code_for_tokens(
                    callback.code,
                    self._verifier,
                    self.redirect_uri,
                    adapter=self._adapter,
                    proxy=self._proxy,
                )
                email = get_user_email(token.access, adapter=self._adapter, proxy=self._proxy)
                project_id = discover_project(
                    token.access, adapter=self._adapter, proxy=self._proxy
                )
                token = AntigravityToken(
                    access=token.access,
                    refresh=token.refresh,
                    expires=token.expires,
                    project_id=project_id,
                    email=email,
                )
                with _token_lock():
                    write_antigravity_token(token)
                verified = load_antigravity_token()
                if verified is None or verified.expires != token.expires:
                    raise AntigravityOAuthError(
                        "Antigravity credentials could not be verified after writing."
                    )
            except Exception as exc:
                self._error = exc
                raise
            self._token = token
            return token

    def _expire(self) -> None:
        with self._lock:
            if self._token is not None or self._error is not None:
                return
            self._error = AntigravityOAuthError("Google sign-in expired. Start again.")
            self._close_locked()

    def _raise_if_finished(self) -> None:
        if self._token is not None:
            return
        if self._error is not None:
            raise self._error

    def _close_locked(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timeout_timer.cancel()
        with suppress(Exception):
            self._server.shutdown()
            self._server.server_close()
        if threading.current_thread() is not self._server_thread:
            self._server_thread.join(timeout=2)


def start_antigravity_oauth_login(
    *,
    adapter: AntigravityAdapter | None = None,
    proxy: str | None = None,
    timeout_s: float = 300,
) -> AntigravityOAuthLoginFlow:
    """Create a non-blocking OAuth flow for browser or pasted-callback completion."""

    adapter = adapter or AntigravityAdapter()
    _require_client_credentials(adapter)
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    result_queue: "queue.Queue[_CallbackResult]" = queue.Queue(maxsize=1)
    server = _make_callback_server(state, result_queue, adapter.callback_port)
    port = server.server_port
    redirect_uri = f"http://localhost:{port}{_CALLBACK_PATH}"
    authorize_url = _build_authorize_url(adapter, redirect_uri, challenge, state)
    return AntigravityOAuthLoginFlow(
        authorization_url=authorize_url,
        redirect_uri=redirect_uri,
        verifier=verifier,
        state=state,
        adapter=adapter,
        proxy=proxy,
        result_queue=result_queue,
        server=server,
        timeout_s=timeout_s,
    )


def login_antigravity_oauth(
    *,
    print_fn: Callable[[str], None] = print,
    adapter: AntigravityAdapter | None = None,
    proxy: str | None = None,
    callback_timeout_s: float = 300,
    browser_opener: Callable[[str], bool] = webbrowser.open,
) -> AntigravityToken:
    """Run the browser flow, persist the token and verify it by reading it back."""

    flow = start_antigravity_oauth_login(
        adapter=adapter, proxy=proxy, timeout_s=callback_timeout_s
    )
    print_fn("Opening Google sign-in in your browser...")
    print_fn(f"If it does not open automatically, visit:\n{flow.authorization_url}")
    with suppress(Exception):
        browser_opener(flow.authorization_url)
    try:
        return flow.wait(callback_timeout_s)
    finally:
        flow.cancel()


# ── Proactive refresher ──


class ProactiveRefresher:
    """Refresh the stored Antigravity token shortly before it expires."""

    def __init__(
        self,
        *,
        adapter: AntigravityAdapter | None = None,
        proxy: str | None = None,
        on_refreshed: Callable[[AntigravityToken], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._adapter = adapter or AntigravityAdapter()
        self._proxy = proxy
        self._on_refreshed = on_refreshed
        self._on_error = on_error
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._attempt = 0
        self._dead_refresh: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while self._running:
            token = load_antigravity_token()
            if token is None:
                await self._sleep(60.0)
                continue
            if token.refresh and self._dead_refresh is not None and token.refresh == self._dead_refresh:
                await self._sleep(60.0)
                continue
            delay_ms = next_refresh_delay_ms(token)
            if delay_ms > 0:
                await self._sleep(min(delay_ms, 60_000) / 1000.0)
                continue
            try:
                refreshed = get_antigravity_oauth_token(
                    adapter=self._adapter, proxy=self._proxy, force_refresh=True
                )
            except AntigravityOAuthReauthRequiredError as exc:
                self._dead_refresh = token.refresh
                if self._on_error is not None:
                    self._on_error(exc)
                await self._sleep(60.0)
                continue
            except AntigravityOAuthError as exc:
                if self._on_error is not None:
                    self._on_error(exc)
                await self._sleep(next_backoff_ms(self._attempt) / 1000.0)
                self._attempt += 1
                continue
            self._attempt = 0
            if self._on_refreshed is not None:
                self._on_refreshed(refreshed)


def start_proactive_refresher(
    *,
    adapter: AntigravityAdapter | None = None,
    proxy: str | None = None,
    on_refreshed: Callable[[AntigravityToken], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> ProactiveRefresher:
    """Start a proactive refresher and return it (tolerates a missing token)."""

    refresher = ProactiveRefresher(
        adapter=adapter,
        proxy=proxy,
        on_refreshed=on_refreshed,
        on_error=on_error,
    )
    refresher.start()
    return refresher


# ── Model catalog ──


def _antigravity_fallback_models() -> tuple[ProviderModelSpec, ...]:
    from nanobot.providers.registry import find_by_name

    spec = find_by_name("google_antigravity")
    return spec.builtin_models if spec is not None else ()


def _is_gemini_model_id(model_id: str) -> bool:
    lowered = model_id.lower()
    return lowered.startswith("gemini-") or lowered.startswith("gemini.")


def _synthetic_tiered_display_name(raw_id: str, all_ids: list[str]) -> str | None:
    """Name a nameless ``<base>-tiered`` model, but only when it has no named siblings.

    Google ships some models *only* under a ``-tiered`` id with no ``displayName``
    (e.g. ``gemini-3.7-flash-tiered``). A plain "no displayName → skip" filter
    would drop them forever, so synthesize a name from the id — unless the same
    base already has named per-tier siblings (``gemini-3.6-flash-low/-medium``),
    in which case the tiered id is a hidden duplicate.
    """

    lower = raw_id.lower()
    if not lower.endswith("-tiered"):
        return None
    base = lower[: -len("-tiered")]
    has_named_sibling = any(
        other != lower and (other == base or other.startswith(f"{base}-"))
        for other in all_ids
    )
    if has_named_sibling:
        return None
    words = [w if w[:1].isdigit() else w[:1].upper() + w[1:] for w in base.split("-")]
    return " ".join(words)


def _normalize_wire_model_id(model_id: str) -> str:
    """Append ``-low`` to bare ``*-pro`` ids (matches the OpenClaw normalization)."""

    trimmed = model_id.strip()
    if trimmed.lower() in {"gemini-3-pro", "gemini-3.1-pro", "gemini-3-1-pro"}:
        return f"{trimmed}-low"
    return trimmed


def _slugify_display_name(name: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"-+", "-", re.sub(r"[\s()]+", "-", name.lower())))


def _dedupe_by_display_name(
    entries: list[ProviderModelSpec],
) -> list[ProviderModelSpec]:
    """Keep one model per display name (prefer ``-agent``, then slug match)."""

    winners: dict[str, ProviderModelSpec] = {}
    for entry in entries:
        existing = winners.get(entry.label)
        if existing is None:
            winners[entry.label] = entry
            continue
        new_wire = entry.id.split("/", 1)[-1]
        old_wire = existing.id.split("/", 1)[-1]
        new_agent = new_wire.endswith("-agent")
        old_agent = old_wire.endswith("-agent")
        if new_agent and not old_agent:
            winners[entry.label] = entry
            continue
        if old_agent and not new_agent:
            continue
        slug = _slugify_display_name(entry.label)
        if new_wire == slug and old_wire != slug:
            winners[entry.label] = entry
    return list(winners.values())


def _parse_antigravity_models(payload: Any) -> tuple[ProviderModelSpec, ...]:
    """Normalise a ``fetchAvailableModels`` payload into catalog specs.

    The payload is an object keyed by model id. We keep every chat-capable model
    with a display name (Gemini, plus Claude/GPT-OSS that Google routes through
    Antigravity), synthesize names for nameless ``-tiered`` models, normalise
    bare ``*-pro`` ids, and drop internal completion models (``tab_*``).
    """

    if not isinstance(payload, dict):
        return ()
    models_obj = cast(dict[str, Any], payload).get("models")
    if not isinstance(models_obj, dict):
        return ()
    raw_items = list(cast(dict[str, Any], models_obj).items())
    all_ids = [str(key).strip().lower() for key, _ in raw_items]
    entries: list[ProviderModelSpec] = []
    seen: set[str] = set()
    for raw_id, raw_model in raw_items:
        wire = str(raw_id).strip()
        if not wire or wire.startswith("tab_"):
            continue
        row = cast(dict[str, Any], raw_model) if isinstance(raw_model, dict) else {}
        label = row.get("displayName") or row.get("display_name")
        if not isinstance(label, str) or not label.strip():
            label = _synthetic_tiered_display_name(wire, all_ids)
        if not label:
            continue
        wire_id = _normalize_wire_model_id(wire)
        if wire_id in seen:
            continue
        seen.add(wire_id)
        raw_context = row.get("maxTokens") or row.get("contextWindow") or row.get("context_window")
        context_window: int | None = (
            int(raw_context)
            if isinstance(raw_context, (int, float))
            and not isinstance(raw_context, bool)
            and raw_context > 0
            else (1_000_000 if _is_gemini_model_id(wire_id) else None)
        )
        entries.append(
            ProviderModelSpec(
                id=f"google-antigravity/{wire_id}",
                label=label.strip(),
                context_window=context_window,
            )
        )
    return tuple(_dedupe_by_display_name(entries))


def _fetch_antigravity_models(proxy: str | None) -> tuple[ProviderModelSpec, ...]:
    adapter = AntigravityAdapter()
    try:
        token = get_antigravity_oauth_token(adapter=adapter, proxy=proxy)
    except AntigravityOAuthReauthRequiredError:
        raise OAuthCatalogAuthRequiredError() from None
    except AntigravityOAuthError as exc:
        raise RuntimeError(str(exc)) from exc
    if not token.project_id:
        raise RuntimeError("Antigravity credentials are missing a project id")
    endpoint = adapter.target_endpoints[0] if adapter.target_endpoints else DEFAULT_ENDPOINT
    client_kwargs: dict[str, Any] = {"timeout": _HTTP_TIMEOUT_S, "follow_redirects": False}
    if proxy:
        client_kwargs.update(proxy=proxy, trust_env=False)
    with httpx.Client(**client_kwargs) as client:
        response = client.post(
            f"{endpoint}/v1internal:fetchAvailableModels",
            json={"project": token.project_id},
            headers=build_headers(adapter, token.access),
        )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Antigravity model list request failed (HTTP {response.status_code})"
        )
    return _parse_antigravity_models(response.json())


_ANTIGRAVITY_OAUTH_MODEL_CATALOG = OAuthModelCatalog(
    fallback_models=_antigravity_fallback_models(),
    fetch=_fetch_antigravity_models,
)


def get_antigravity_oauth_model_catalog(
    proxy: str | None = None,
) -> OAuthModelCatalogSnapshot:
    cache_key = f"{get_antigravity_oauth_storage_path()}\0{proxy or ''}"
    return _ANTIGRAVITY_OAUTH_MODEL_CATALOG.get(cache_key=cache_key, proxy=proxy)


def invalidate_antigravity_oauth_model_catalog() -> None:
    _ANTIGRAVITY_OAUTH_MODEL_CATALOG.invalidate()
