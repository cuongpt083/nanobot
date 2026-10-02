"""Data-driven adapter for the Google Antigravity (``agy``) OAuth provider.

This module holds the *volatile identity surface* of the Antigravity wire
protocol — endpoint, User-Agent version, OAuth client id/secret, redirect,
model-id aliases and header/body overrides — as configuration rather than code,
so a Google-side change (a version bump, a model rename, an extra header) can be
absorbed by editing config instead of shipping a new release.

It reuses the *engine* of :mod:`nanobot.providers.patcher.rules` (template
render + version comparison) but none of the Anthropic-specific proxy.

.. warning::
   This provider impersonates the ``agy`` client (User-Agent, ``Client-Metadata``,
   a borrowed project id and a Google OAuth client supplied via config/env or
   detected from a local Gemini CLI / Antigravity CLI) to use a Google
   subscription from a third-party app. That may violate Google's terms of
   service and risks account action. Prefer Google AI Studio / Vertex AI API keys.
   Kept for interoperability study on accounts you own; disabled by default.
"""

from __future__ import annotations

import os
import platform as platform_module
import re
import shutil
import sys
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from nanobot.providers.patcher.rules import compare_versions, render_template

#: Cloud Code Assist host actually used by ``agy`` (the electron layer rewrote
#: the sandbox host to this one, and the agy logs confirm it).
DEFAULT_ENDPOINT = "https://daily-cloudcode-pa.googleapis.com"
DEFAULT_ENDPOINT_FALLBACKS: tuple[str, ...] = ("https://cloudcode-pa.googleapis.com",)

#: User-Agent version advertised to Antigravity. This decides the *tier* Google
#: grants ("Antigravity" vs "Gemini Code Assist"), so it is treated as an
#: app-managed floor: an update may raise it, a persisted value must not lower it.
DEFAULT_USER_AGENT_VERSION = "1.21.9"

#: Google OAuth client credentials are deliberately NOT shipped in source: a
#: bundled client secret trips secret scanners and cannot be rotated without a
#: release. Provide them via the environment or per-provider config
#: (``provider.antigravity.client_id`` / ``client_secret``); otherwise they are
#: borrowed from a local ``gemini-cli`` / ``agy`` install at runtime.
CLIENT_ID_ENV_VAR = "NANOBOT_ANTIGRAVITY_CLIENT_ID"
CLIENT_SECRET_ENV_VAR = "NANOBOT_ANTIGRAVITY_CLIENT_SECRET"

#: Public Gemini CLI shared client id. A local ``agy`` install bundles both this
#: client and Antigravity's own dedicated one, so prefer the shared client (the
#: one ``agy`` actually authenticates with) when several are found.
SHARED_CLIENT_ID_PREFIX = "1071006060591-"

#: The shared Gemini CLI client is public, but a literal copy still trips secret
#: scanners, so when neither config nor the environment provides one it is read
#: from a local ``gemini-cli`` / ``agy`` install (see
#: :func:`discover_local_client_credentials`). The match is deliberately narrow
#: so a random scanner hit cannot substitute an unrelated OAuth client.
_CLIENT_ID_PATTERN = re.compile(rb"(\d{10,}-[a-z0-9]+\.apps\.googleusercontent\.com)")
#: Google issues ``GOCSPX-`` secrets with a fixed 28-character body; matching the
#: exact length keeps two adjacent secrets from being captured as one run.
_CLIENT_SECRET_PATTERN = re.compile(rb"(GOCSPX-[A-Za-z0-9_-]{28})")
_SCAN_CHUNK_BYTES = 1024 * 1024
_SCAN_OVERLAP_BYTES = 256

DEFAULT_REDIRECT_URI = "http://localhost:51121/oauth-callback"
DEFAULT_CALLBACK_PORT = 51121

DEFAULT_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DEFAULT_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo?alt=json"

#: Superset of the scopes used by the electron and pi-ai implementations.
#: ``aicode`` is the important one — without it chat 403s with
#: ``cloudaicompanion.companions.generateCode``.
DEFAULT_SCOPES: tuple[str, ...] = (
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/aicode",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs",
)

#: Fallback project when ``loadCodeAssist`` yields nothing and no local ``agy``
#: cache can be borrowed (matches pi-ai / electron).
DEFAULT_PROJECT_ID = "rising-fact-p41fc"

#: System prelude injected ahead of the real system instruction (from pi-ai).
ANTIGRAVITY_SYSTEM_INSTRUCTION = (
    "You are Antigravity, a powerful agentic AI coding assistant designed by the "
    "Google Deepmind team working on Advanced Agentic Coding."
    "You are pair programming with a USER to solve their coding task. The task may "
    "require creating a new codebase, modifying or debugging an existing codebase, "
    "or simply answering a question."
    "**Absolute paths only**"
    "**Proactiveness**"
)

CLIENT_METADATA = {
    "ideType": "IDE_UNSPECIFIED",
    "platform": "PLATFORM_UNSPECIFIED",
    "pluginType": "GEMINI",
}

#: Beta header required when a Claude model runs through Antigravity with reasoning.
CLAUDE_THINKING_BETA_HEADER = "interleaved-thinking-2025-05-14"

#: Default model-id normalisation (Patch AGM equivalents). Bare ``*-pro`` ids need
#: a ``-low`` routing suffix; the stale ``gemini-3.1-pro-high`` maps to
#: Google's canonical agent id.
DEFAULT_MODEL_ALIASES: dict[str, str] = {
    "gemini-3-pro": "gemini-3-pro-low",
    "gemini-3.1-pro": "gemini-3.1-pro-low",
    "gemini-3-1-pro": "gemini-3-1-pro-low",
    "gemini-3.1-pro-high": "gemini-pro-agent",
}


def _default_platform_label() -> str:
    """Return the ``<os>`` token Antigravity's User-Agent carries."""

    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _default_arch_label() -> str:
    machine = platform_module.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x64"
    if machine in {"aarch64", "arm64"}:
        return "arm64"
    return machine or "x64"


def _env(name: str) -> str:
    """Read a non-empty, whitespace-trimmed environment value (else ``""``)."""

    value = os.environ.get(name)
    return value.strip() if value and value.strip() else ""


def _node_global_module_roots() -> list[Path]:
    """Best-effort global ``node_modules`` roots without shelling out to npm."""

    candidates: list[Path] = [
        Path.home() / ".bun" / "install" / "global" / "node_modules",
        Path.home() / ".npm-global" / "lib" / "node_modules",
        Path("/usr/local/lib/node_modules"),
        Path("/usr/lib/node_modules"),
    ]
    candidates.extend(sorted(Path.home().glob(".nvm/versions/node/*/lib/node_modules")))
    appdata = os.environ.get("APPDATA")
    if appdata:
        npm = Path(appdata) / "npm" / "node_modules"
        candidates.append(npm)
        candidates.extend(sorted((Path(appdata) / "nvm").glob("v*/node_modules")))
        candidates.extend(sorted((Path(appdata) / "nvm").glob("installs/v*/node_modules")))
    return [path for path in candidates if path.is_dir()]


def _candidate_client_files() -> list[Path]:
    """Files that may embed the shared Gemini CLI OAuth client, cheapest first."""

    files: list[Path] = []
    for root in _node_global_module_roots():
        package = root / "@google" / "gemini-cli"
        if package.is_dir():
            files.extend(sorted(package.rglob("*.js")))
    on_path = shutil.which("agy")
    if on_path:
        files.append(Path(on_path))
    for raw in (
        "~/.local/bin/agy",
        "~/.antigravity/bin/agy",
        "~/.antigravity-cli/bin/agy",
        "/usr/local/bin/agy",
    ):
        path = Path(raw).expanduser()
        if path.is_file():
            files.append(path)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        windows_binary = Path(local_app_data) / "agy" / "bin" / "agy.exe"
        if windows_binary.is_file():
            files.append(windows_binary)
    seen: list[Path] = []
    for path in files:
        if path not in seen:
            seen.append(path)
    return seen


def _dedupe(values: list[str]) -> list[str]:
    """Order-preserving de-duplication (chunk overlap can re-scan a match)."""

    seen: list[str] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _scan_file_for_client(path: Path) -> tuple[list[str], list[str]]:
    """Collect every Google OAuth client id/secret embedded in a file."""

    ids: list[str] = []
    secrets: list[str] = []
    try:
        with path.open("rb") as handle:
            carry = b""
            while chunk := handle.read(_SCAN_CHUNK_BYTES):
                window = carry + chunk
                ids.extend(m.group(1).decode() for m in _CLIENT_ID_PATTERN.finditer(window))
                secrets.extend(
                    m.group(1).decode() for m in _CLIENT_SECRET_PATTERN.finditer(window)
                )
                carry = window[-_SCAN_OVERLAP_BYTES:]
    except OSError:
        return [], []
    return _dedupe(ids), _dedupe(secrets)


@lru_cache(maxsize=1)
def discover_local_client_credentials() -> tuple[str, tuple[str, ...]] | None:
    """Borrow the OAuth client embedded in a local ``gemini-cli`` or ``agy``.

    Returns ``(client_id, candidate_secrets)`` for the first local install that
    exposes a client, preferring the Gemini CLI shared client. A file can contain
    several clients (Antigravity bundles a dedicated one too) but the binary does
    not encode which secret pairs with which id, so every secret found is
    returned in order and the caller retries until Google accepts one. Cached per
    process because scanning a large ``agy`` binary is not free.
    """

    fallback: tuple[str, tuple[str, ...]] | None = None
    for path in _candidate_client_files():
        ids, secrets = _scan_file_for_client(path)
        if not ids or not secrets:
            continue
        client_id = next(
            (value for value in ids if value.startswith(SHARED_CLIENT_ID_PREFIX)), ids[0]
        )
        found = (client_id, tuple(secrets))
        if client_id.startswith(SHARED_CLIENT_ID_PREFIX):
            return found
        if fallback is None:
            fallback = found
    return fallback


@dataclass
class AntigravityAdapter:
    """Runtime configuration for the Antigravity provider (data, not code)."""

    enabled: bool = False
    endpoint: str = DEFAULT_ENDPOINT
    endpoint_fallbacks: tuple[str, ...] = DEFAULT_ENDPOINT_FALLBACKS
    user_agent_version: str = DEFAULT_USER_AGENT_VERSION
    client_id: str = field(default_factory=lambda: _env(CLIENT_ID_ENV_VAR))
    client_secret: str = field(default_factory=lambda: _env(CLIENT_SECRET_ENV_VAR))
    client_secret_candidates: tuple[str, ...] = ()
    redirect_uri: str = DEFAULT_REDIRECT_URI
    callback_port: int = DEFAULT_CALLBACK_PORT
    authorize_url: str = DEFAULT_AUTHORIZE_URL
    token_url: str = DEFAULT_TOKEN_URL
    revoke_url: str = DEFAULT_REVOKE_URL
    userinfo_url: str = DEFAULT_USERINFO_URL
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    project_id: str | None = None
    model_aliases: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODEL_ALIASES))
    header_overrides: dict[str, str] = field(default_factory=dict)
    body_overrides: dict[str, Any] = field(default_factory=dict)
    request_overrides: dict[str, Any] = field(default_factory=dict)
    inject_system_instruction: bool = True
    request_type: str = "agent"
    user_agent_label: str = "antigravity"
    #: Optional outbound HTTP(S) proxy for the upstream connection.
    proxy: str | None = None

    @property
    def target_endpoints(self) -> tuple[str, ...]:
        """Endpoint chain: primary first, then fallbacks (de-duplicated)."""

        chain = [self.endpoint, *self.endpoint_fallbacks]
        seen: list[str] = []
        for item in chain:
            normalized = item.rstrip("/")
            if normalized and normalized not in seen:
                seen.append(normalized)
        return tuple(seen)


def resolve_user_agent_version(stored: str | None, shipped: str = DEFAULT_USER_AGENT_VERSION) -> str:
    """Keep the shipped User-Agent version as a floor, honour a higher/custom value."""

    if stored and compare_versions(stored, shipped) >= 0:
        return stored
    return shipped


def normalize_model_id(model: str, aliases: dict[str, str] | None = None) -> str:
    """Apply the routing-suffix map to a bare wire model id."""

    table = DEFAULT_MODEL_ALIASES if aliases is None else aliases
    return table.get(model, model)


def render_user_agent(
    adapter: AntigravityAdapter,
    *,
    platform_label: str | None = None,
    arch_label: str | None = None,
) -> str:
    """Build ``antigravity/<version> <os>/<arch>``."""

    version = resolve_user_agent_version(adapter.user_agent_version)
    os_label = platform_label or _default_platform_label()
    arch = arch_label or _default_arch_label()
    return render_template(
        f"{adapter.user_agent_label}/{{{{version}}}} {os_label}/{arch}",
        version=version,
    )


def build_headers(
    adapter: AntigravityAdapter,
    access_token: str,
    *,
    reasoning_claude: bool = False,
) -> dict[str, str]:
    """Build the full Antigravity request header set, then apply overrides."""

    headers: dict[str, str] = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": render_user_agent(adapter),
        "Client-Metadata": _json_metadata(),
    }
    if reasoning_claude:
        headers["anthropic-beta"] = CLAUDE_THINKING_BETA_HEADER
    for name, value in adapter.header_overrides.items():
        headers[name] = value
    return headers


def _json_metadata() -> str:
    import json

    return json.dumps(CLIENT_METADATA, separators=(",", ":"))


def apply_overrides(wrapper: dict[str, Any], adapter: AntigravityAdapter) -> dict[str, Any]:
    """Shallow-merge configured body/request overrides into the request wrapper."""

    result: dict[str, Any] = dict(wrapper)
    if adapter.body_overrides:
        result.update(adapter.body_overrides)
    if adapter.request_overrides:
        request = result.get("request")
        request_dict = cast(dict[str, Any], request) if isinstance(request, dict) else {}
        merged_request = {**request_dict, **adapter.request_overrides}
        result["request"] = merged_request
    return result


def adapter_with_version_floor(adapter: AntigravityAdapter) -> AntigravityAdapter:
    """Return a copy with the User-Agent version lifted to the shipped floor."""

    return replace(
        adapter,
        user_agent_version=resolve_user_agent_version(adapter.user_agent_version),
    )


def build_adapter(settings: Any | None = None, *, proxy: str | None = None) -> AntigravityAdapter:
    """Build an adapter from an ``AntigravitySettings``-shaped object (or defaults).

    Kept duck-typed (``getattr``) so this module never imports the config schema,
    which would create an import cycle.
    """

    def _get(name: str, default: Any) -> Any:
        value = getattr(settings, name, None) if settings is not None else None
        return default if value is None else value

    fallbacks = _get("endpoint_fallbacks", DEFAULT_ENDPOINT_FALLBACKS)
    client_id = _get("client_id", "") or _env(CLIENT_ID_ENV_VAR)
    client_secret = _get("client_secret", "") or _env(CLIENT_SECRET_ENV_VAR)
    client_secret_candidates: tuple[str, ...] = ()
    if not (client_id and client_secret):
        discovered = discover_local_client_credentials()
        if discovered is not None:
            discovered_id, discovered_secrets = discovered
            client_id = client_id or discovered_id
            if not client_secret and discovered_secrets:
                client_secret = discovered_secrets[0]
                client_secret_candidates = discovered_secrets[1:]
    return AntigravityAdapter(
        enabled=bool(_get("enabled", False)),
        endpoint=_get("endpoint", DEFAULT_ENDPOINT) or DEFAULT_ENDPOINT,
        endpoint_fallbacks=tuple(fallbacks),
        user_agent_version=_get("user_agent_version", DEFAULT_USER_AGENT_VERSION)
        or DEFAULT_USER_AGENT_VERSION,
        client_id=client_id,
        client_secret=client_secret,
        client_secret_candidates=client_secret_candidates,
        redirect_uri=_get("redirect_uri", DEFAULT_REDIRECT_URI) or DEFAULT_REDIRECT_URI,
        callback_port=int(_get("callback_port", DEFAULT_CALLBACK_PORT)),
        scopes=tuple(_get("scopes", None) or DEFAULT_SCOPES),
        project_id=_get("project_id", None),
        model_aliases=dict(_get("model_aliases", None) or DEFAULT_MODEL_ALIASES),
        header_overrides=dict(_get("header_overrides", None) or {}),
        body_overrides=dict(_get("body_overrides", None) or {}),
        request_overrides=dict(_get("request_overrides", None) or {}),
        inject_system_instruction=bool(_get("inject_system_instruction", True)),
        request_type=_get("request_type", "agent") or "agent",
        user_agent_label=_get("user_agent_label", "antigravity") or "antigravity",
        proxy=proxy,
    )
