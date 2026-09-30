"""Anthropic subscription OAuth (Authorization Code + PKCE) support.

Implements the same browser flow the Claude Code CLI uses, but natively in
nanobot: PKCE, a loopback callback server, JSON token exchange (Anthropic's
token endpoint is non-standard and expects JSON, not form encoding) and
rotation-aware refresh.

.. warning::
   Anthropic's terms of service only permit subscription OAuth tokens inside
   Anthropic's own products; a third-party app must use an Anthropic Console API
   key. This module exists for interoperability study on accounts you own. See
   ``docs/plan-anthropic-patcher-proxy.md``.

The refresh-token lifecycle is the interesting part: tokens rotate on every
refresh and reuse revokes the whole family, so credentials are distributed state
across processes. This module keeps a single source of truth on disk guarded by
an inter-process file lock.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import queue
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
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from filelock import FileLock
from loguru import logger

from nanobot.config.paths import get_data_dir
from nanobot.utils.helpers import _write_text_atomic  # pyright: ignore[reportPrivateUsage]

ANTHROPIC_OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
ANTHROPIC_OAUTH_TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
ANTHROPIC_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
ANTHROPIC_OAUTH_SCOPES = (
    "user:profile",
    "user:inference",
    "user:sessions:claude_code",
    "user:mcp_servers",
    "user:file_upload",
)

#: Refresh this long before the stored expiry (which itself is 5 min shy of the
#: server expiry) so the refresh token never lapses while the app is idle.
REFRESH_LEAD_MS = 10 * 60 * 1000
#: Safety margin subtracted from ``expires_in`` when persisting.
EXPIRY_MARGIN_MS = 5 * 60 * 1000
_DEFAULT_TOKEN_TTL_S = 8 * 60 * 60
_HTTP_TIMEOUT_S = 15.0
_PROACTIVE_BACKOFF_MS = (5, 10, 20, 40, 60)
_PROACTIVE_MAX_BACKOFF_MS = 60 * 60 * 1000


class AnthropicOAuthError(RuntimeError):
    """An actionable Anthropic OAuth failure with no credential material."""


class AnthropicOAuthReauthRequiredError(AnthropicOAuthError):
    """No usable login remains; an explicit sign-in is required."""


@dataclass(frozen=True)
class AnthropicToken:
    """Persisted Anthropic OAuth token material."""

    access: str
    refresh: str | None
    expires: int

    @classmethod
    def from_dict(cls, value: Any) -> AnthropicToken | None:
        if not isinstance(value, dict):
            return None
        data = cast(dict[str, Any], value)
        access = data.get("access")
        refresh = data.get("refresh")
        expires = data.get("expires")
        if not isinstance(access, str) or not access:
            return None
        if not isinstance(expires, int):
            return None
        return cls(
            access=access,
            refresh=refresh if isinstance(refresh, str) and refresh else None,
            expires=expires,
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


def token_is_fresh(token: AnthropicToken, *, min_ttl_ms: int = 0) -> bool:
    """True when the access token outlives ``min_ttl_ms`` from now."""

    return bool(token.access) and token.expires > _now_ms() + max(0, min_ttl_ms)


def is_permanent_grant_failure(status_code: int, body: str) -> bool:
    """Classify a token-endpoint failure as permanent (needs re-login).

    ``429``/``5xx`` are temporary — retrying a live account matters more than
    dropping one on a transient blip. Unknown bodies are treated as temporary so
    a still-good account is never abandoned.
    """

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
    token: AnthropicToken, *, now: int | None = None, lead_ms: int = REFRESH_LEAD_MS
) -> int:
    """Milliseconds until proactive refresh should fire (never negative)."""

    reference = _now_ms() if now is None else now
    return max(0, token.expires - lead_ms - reference)


# ── Storage (single source of truth + inter-process lock) ──


def get_anthropic_oauth_storage_path() -> Path:
    """Return the instance-scoped Anthropic OAuth credential path."""

    return get_data_dir() / "auth" / "anthropic.json"


def _token_lock() -> FileLock:
    path = get_anthropic_oauth_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(path.with_suffix(".lock")), timeout=120)


def load_anthropic_token() -> AnthropicToken | None:
    path = get_anthropic_oauth_storage_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not read Anthropic OAuth credentials: {}", type(exc).__name__)
        return None
    return AnthropicToken.from_dict(payload)


def write_anthropic_token(token: AnthropicToken) -> None:
    path = get_anthropic_oauth_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        os.chmod(path.parent, 0o700)
    _write_text_atomic(path, json.dumps(asdict(token), indent=2, ensure_ascii=False))
    with suppress(OSError):
        os.chmod(path, 0o600)


def logout_anthropic_oauth() -> bool:
    path = get_anthropic_oauth_storage_path()
    with _token_lock():
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True


def get_anthropic_oauth_login_status() -> AnthropicToken | None:
    return load_anthropic_token()


# ── Token endpoint ──


def _http_client(proxy: str | None) -> httpx.Client:
    kwargs: dict[str, Any] = {"timeout": _HTTP_TIMEOUT_S}
    if proxy:
        kwargs.update(proxy=proxy, trust_env=False)
    return httpx.Client(**kwargs)


def _token_from_response(
    payload: dict[str, Any], previous_refresh: str | None = None
) -> AnthropicToken:
    access = payload.get("access_token")
    if not isinstance(access, str) or not access:
        raise AnthropicOAuthError("Anthropic sign-in returned no access token.")
    try:
        expires_in = max(1, int(payload.get("expires_in") or _DEFAULT_TOKEN_TTL_S))
    except (TypeError, ValueError):
        expires_in = _DEFAULT_TOKEN_TTL_S
    refresh = payload.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        refresh = previous_refresh
    # Persist 5 minutes shy of true expiry for clock skew.
    return AnthropicToken(
        access=access,
        refresh=refresh,
        expires=_now_ms() + expires_in * 1000 - EXPIRY_MARGIN_MS,
    )


def exchange_code_for_tokens(
    code: str,
    verifier: str,
    redirect_uri: str,
    state: str,
    *,
    proxy: str | None = None,
    client: httpx.Client | None = None,
) -> AnthropicToken:
    """Exchange an authorization code. Anthropic expects JSON, not form encoding."""

    body = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": ANTHROPIC_OAUTH_CLIENT_ID,
        "code_verifier": verifier,
        "state": state,
    }
    owns_client = client is None
    http_client = client or _http_client(proxy)
    try:
        response = http_client.post(
            ANTHROPIC_OAUTH_TOKEN_URL,
            json=body,
            headers={"Content-Type": "application/json"},
        )
    finally:
        if owns_client:
            http_client.close()
    if response.status_code >= 400:
        raise AnthropicOAuthError(
            f"Anthropic token exchange failed (HTTP {response.status_code})."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AnthropicOAuthError("Anthropic sign-in returned an invalid token response.") from exc
    if not isinstance(payload, dict):
        raise AnthropicOAuthError("Anthropic sign-in returned no access token.")
    return _token_from_response(cast(dict[str, Any], payload))


def refresh_anthropic_token(
    refresh_token: str,
    *,
    proxy: str | None = None,
    client: httpx.Client | None = None,
) -> AnthropicToken:
    """Refresh under rotation. Never sends ``scope`` (Anthropic rejects it)."""

    body = {
        "grant_type": "refresh_token",
        "client_id": ANTHROPIC_OAUTH_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    owns_client = client is None
    http_client = client or _http_client(proxy)
    try:
        response = http_client.post(
            ANTHROPIC_OAUTH_TOKEN_URL,
            json=body,
            headers={"Content-Type": "application/json"},
        )
    finally:
        if owns_client:
            http_client.close()
    if response.status_code >= 400:
        body_text = response.text
        if is_permanent_grant_failure(response.status_code, body_text):
            raise AnthropicOAuthReauthRequiredError(
                "The Anthropic login has expired. Please sign in again."
            )
        raise AnthropicOAuthError(
            f"Anthropic token refresh failed (HTTP {response.status_code})."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise AnthropicOAuthError("Anthropic refresh returned an invalid token response.") from exc
    if not isinstance(payload, dict):
        raise AnthropicOAuthError("Anthropic refresh returned no access token.")
    return _token_from_response(cast(dict[str, Any], payload), previous_refresh=refresh_token)


def get_anthropic_oauth_token(
    *,
    proxy: str | None = None,
    min_ttl_ms: int = REFRESH_LEAD_MS,
    force_refresh: bool = False,
) -> AnthropicToken:
    """Load a usable token, refreshing under an inter-process lock when needed."""

    token = load_anthropic_token()
    if token is None:
        raise AnthropicOAuthReauthRequiredError(
            "Anthropic is not signed in. Run `nanobot provider login anthropic-oauth` first."
        )
    if not force_refresh and token_is_fresh(token, min_ttl_ms=min_ttl_ms):
        return token
    if not token.refresh:
        if not force_refresh and token_is_fresh(token):
            return token
        raise AnthropicOAuthReauthRequiredError(
            "The Anthropic login has expired and cannot be refreshed. Sign in again."
        )

    with _token_lock():
        # Re-read under the lock: another process may have rotated while we waited.
        latest = load_anthropic_token()
        if latest is None:
            raise AnthropicOAuthReauthRequiredError("Anthropic credentials disappeared.")
        if not force_refresh and token_is_fresh(latest, min_ttl_ms=min_ttl_ms):
            return latest
        if not latest.refresh:
            return latest
        refreshed = refresh_anthropic_token(latest.refresh, proxy=proxy)
        write_anthropic_token(refreshed)
        logger.info("Anthropic OAuth token refreshed")
        return refreshed


# ── Browser login flow ──


def _build_authorize_url(redirect_uri: str, challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": ANTHROPIC_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": " ".join(ANTHROPIC_OAUTH_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{ANTHROPIC_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


@dataclass
class _CallbackResult:
    code: str
    state: str


def _make_callback_server(
    state: str, result_queue: queue.Queue[_CallbackResult]
) -> ThreadingHTTPServer:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
            parsed = urlsplit(self.path)
            if parsed.path != "/callback":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            params = parse_qs(parsed.query)
            received_state = (params.get("state") or [""])[0]
            code = (params.get("code") or [""])[0]
            if received_state != state or not code:
                self.send_response(HTTPStatus.BAD_REQUEST)
                self.end_headers()
                self.wfile.write(b"Invalid OAuth callback.")
                return
            result_queue.put(_CallbackResult(code=code, state=received_state))
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h2>Anthropic sign-in complete.</h2>You can close this tab.")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    return server


def _parse_authorization_response(value: str, expected_state: str) -> str:
    """Accept either a bare authorization code or a full callback URL."""

    raw = value.strip()
    if not raw:
        raise AnthropicOAuthError("No authorization code was provided.")
    if "code=" in raw:
        params = parse_qs(urlsplit(raw).query)
        received_state = (params.get("state") or [""])[0]
        if expected_state and received_state and received_state != expected_state:
            raise AnthropicOAuthError("OAuth state mismatch. Start the sign-in again.")
        code = (params.get("code") or [""])[0]
        if not code:
            raise AnthropicOAuthError("No authorization code found in the callback URL.")
        return code
    return raw


class AnthropicOAuthLoginFlow:
    """Pending Anthropic OAuth login that can finish via loopback or a pasted code."""

    def __init__(
        self,
        *,
        authorization_url: str,
        redirect_uri: str,
        verifier: str,
        state: str,
        proxy: str | None,
        result_queue: queue.Queue[_CallbackResult],
        server: ThreadingHTTPServer,
        timeout_s: float,
    ) -> None:
        self.authorization_url = authorization_url
        self.redirect_uri = redirect_uri
        self._verifier = verifier
        self._state = state
        self._proxy = proxy
        self._result_queue = result_queue
        self._server = server
        self._expires_at = time.monotonic() + timeout_s
        self._lock = threading.Lock()
        self._token: AnthropicToken | None = None
        self._error: Exception | None = None
        self._closed = False
        self._server_thread = threading.Thread(
            target=server.serve_forever,
            name="nanobot-anthropic-oauth-callback",
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

    def complete(self, authorization_response: str | None = None) -> AnthropicToken | None:
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

    def wait(self, timeout_s: float) -> AnthropicToken:
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
            raise AnthropicOAuthError("Timed out waiting for Anthropic sign-in.") from exc
        return self._finish(callback)

    def cancel(self) -> None:
        """Stop the callback listener for an abandoned flow."""

        with self._lock:
            if self._token is None and self._error is None:
                self._error = AnthropicOAuthError("Anthropic sign-in was cancelled.")
            self._close_locked()

    def _finish(self, callback: _CallbackResult) -> AnthropicToken:
        with self._lock:
            if self._token is not None:
                return self._token
            self._raise_if_finished()
            self._close_locked()
            try:
                if callback.state and callback.state != self._state:
                    raise AnthropicOAuthError("OAuth state mismatch. Start the sign-in again.")
                token = exchange_code_for_tokens(
                    callback.code,
                    self._verifier,
                    self.redirect_uri,
                    self._state,
                    proxy=self._proxy,
                )
                with _token_lock():
                    write_anthropic_token(token)
                verified = load_anthropic_token()
                if verified is None or verified.expires != token.expires:
                    raise AnthropicOAuthError(
                        "Anthropic credentials could not be verified after writing."
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
            self._error = AnthropicOAuthError("Anthropic sign-in expired. Start again.")
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


def start_anthropic_oauth_login(
    *, proxy: str | None = None, timeout_s: float = 300
) -> AnthropicOAuthLoginFlow:
    """Create a non-blocking OAuth flow for browser or pasted-callback completion."""

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    result_queue: queue.Queue[_CallbackResult] = queue.Queue(maxsize=1)
    server = _make_callback_server(state, result_queue)
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    authorize_url = _build_authorize_url(redirect_uri, challenge, state)
    return AnthropicOAuthLoginFlow(
        authorization_url=authorize_url,
        redirect_uri=redirect_uri,
        verifier=verifier,
        state=state,
        proxy=proxy,
        result_queue=result_queue,
        server=server,
        timeout_s=timeout_s,
    )


def login_anthropic_oauth(
    *,
    print_fn: Callable[[str], None] = print,
    proxy: str | None = None,
    callback_timeout_s: float = 300,
    browser_opener: Callable[[str], bool] = webbrowser.open,
) -> AnthropicToken:
    """Run the browser flow, persist the token and verify it by reading it back."""

    flow = start_anthropic_oauth_login(proxy=proxy, timeout_s=callback_timeout_s)
    print_fn("Opening Anthropic sign-in in your browser...")
    print_fn(f"If it does not open automatically, visit:\n{flow.authorization_url}")
    with suppress(Exception):
        browser_opener(flow.authorization_url)
    try:
        return flow.wait(callback_timeout_s)
    finally:
        flow.cancel()


# ── Proactive refresher ──


class ProactiveRefresher:
    """Refresh the stored Anthropic token shortly before it expires.

    Guards against the failure mode where an idle access token expires, the
    refresh token lapses with it, and the user must sign in again. Also remembers
    a rejected refresh token so a stray restart cannot spin a hopeless retry loop.
    """

    def __init__(
        self,
        *,
        proxy: str | None = None,
        on_refreshed: Callable[[AnthropicToken], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
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
            token = load_anthropic_token()
            if token is None:
                await self._sleep(60.0)
                continue
            if token.refresh and self._dead_refresh is not None and token.refresh == self._dead_refresh:
                # Rejected token is still on disk; wait for a re-login to replace it.
                await self._sleep(60.0)
                continue
            delay_ms = next_refresh_delay_ms(token)
            if delay_ms > 0:
                await self._sleep(min(delay_ms, 60_000) / 1000.0)
                continue
            try:
                refreshed = get_anthropic_oauth_token(proxy=self._proxy, force_refresh=True)
            except AnthropicOAuthReauthRequiredError as exc:
                self._dead_refresh = token.refresh
                if self._on_error is not None:
                    self._on_error(exc)
                # Stop attempting until the token on disk changes.
                await self._sleep(60.0)
                continue
            except AnthropicOAuthError as exc:
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
    proxy: str | None = None,
    on_refreshed: Callable[[AnthropicToken], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> ProactiveRefresher | None:
    """Start a proactive refresher when an Anthropic token exists.

    Returns ``None`` (and does nothing) when no token is stored, so callers can
    wire this unconditionally into a startup hook.
    """

    if load_anthropic_token() is None:
        return None
    refresher = ProactiveRefresher(
        proxy=proxy,
        on_refreshed=on_refreshed,
        on_error=on_error,
    )
    refresher.start()
    return refresher
