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
   a borrowed project id and a Google OAuth client you supply) to use a Google
   subscription from a third-party app. That may violate Google's terms of
   service and risks account action. Prefer Google AI Studio / Vertex AI API keys.
   Kept for interoperability study on accounts you own; disabled by default.
"""

from __future__ import annotations

import os
import platform as platform_module
import sys
from dataclasses import dataclass, field, replace
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
#: release. Provide them via the environment, or per-provider config
#: (``provider.antigravity.client_id`` / ``client_secret``).
CLIENT_ID_ENV_VAR = "NANOBOT_ANTIGRAVITY_CLIENT_ID"
CLIENT_SECRET_ENV_VAR = "NANOBOT_ANTIGRAVITY_CLIENT_SECRET"

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


@dataclass
class AntigravityAdapter:
    """Runtime configuration for the Antigravity provider (data, not code)."""

    enabled: bool = False
    endpoint: str = DEFAULT_ENDPOINT
    endpoint_fallbacks: tuple[str, ...] = DEFAULT_ENDPOINT_FALLBACKS
    user_agent_version: str = DEFAULT_USER_AGENT_VERSION
    client_id: str = field(default_factory=lambda: _env(CLIENT_ID_ENV_VAR))
    client_secret: str = field(default_factory=lambda: _env(CLIENT_SECRET_ENV_VAR))
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

    if settings is None:
        return AntigravityAdapter(proxy=proxy)

    def _get(name: str, default: Any) -> Any:
        value = getattr(settings, name, None)
        return default if value is None else value

    fallbacks = _get("endpoint_fallbacks", DEFAULT_ENDPOINT_FALLBACKS)
    return AntigravityAdapter(
        enabled=bool(_get("enabled", False)),
        endpoint=_get("endpoint", DEFAULT_ENDPOINT) or DEFAULT_ENDPOINT,
        endpoint_fallbacks=tuple(fallbacks),
        user_agent_version=_get("user_agent_version", DEFAULT_USER_AGENT_VERSION)
        or DEFAULT_USER_AGENT_VERSION,
        client_id=_get("client_id", "") or _env(CLIENT_ID_ENV_VAR),
        client_secret=_get("client_secret", "") or _env(CLIENT_SECRET_ENV_VAR),
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
