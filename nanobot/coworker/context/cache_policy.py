"""Provider prompt-cache retention policies, TTLs, and ping limits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from nanobot.providers import registry


@dataclass(frozen=True)
class CacheTtlPolicy:
    ttl_s: float
    lead_s: float
    ping_cap: int
    guaranteed: bool


def provider_family(provider: Any) -> tuple[str, str]:
    """Return (provider_name, backend) for an LLMProvider instance or test mock."""
    name = str(getattr(provider, "provider_name", "") or "").strip().lower()
    spec = registry.find_by_name(name) if name else None
    backend = (spec.backend if spec else getattr(provider, "backend", "")) or ""
    return name, str(backend).strip().lower()


def supports_ttl1h(provider: Any) -> bool:
    """Return True only when the provider is direct Anthropic API."""
    name, backend = provider_family(provider)
    return backend == "anthropic" and name == "anthropic"


def resolve(
    provider: Any,
    model: str,
    *,
    retention: Literal["short", "long"] = "short",
    ttl_override: int | None = None,
) -> CacheTtlPolicy | None:
    """Resolve cache TTL and ping policy for a provider and model.

    Returns None for providers without a defined cache retention policy.
    """
    name, backend = provider_family(provider)
    model_lower = (model or "").lower()

    # 1. Anthropic family
    if backend == "anthropic" or name == "anthropic" or "claude" in model_lower:
        direct = name == "anthropic" and backend == "anthropic"
        ttl = 3600.0 if (retention == "long" and direct) else 300.0
        return CacheTtlPolicy(
            ttl_s=float(ttl_override) if ttl_override and ttl_override >= 30 else ttl,
            lead_s=60.0,
            ping_cap=6,
            guaranteed=direct,
        )

    # 2. OpenAI family
    if (
        name in {"openai", "openai_codex"}
        or (backend in {"openai_compat", "openai_codex"} and any(k in model_lower for k in ("gpt-", "o1", "o3", "chatgpt")))
        or (not backend and any(k in model_lower for k in ("gpt-", "o1", "o3", "chatgpt")))
    ):
        return CacheTtlPolicy(
            ttl_s=float(ttl_override) if ttl_override and ttl_override >= 30 else 300.0,
            lead_s=60.0,
            ping_cap=4,
            guaranteed=False,
        )

    # 3. Gemini / Google / Antigravity family
    if name in {"gemini", "google", "antigravity"} or "gemini" in model_lower:
        return CacheTtlPolicy(
            ttl_s=float(ttl_override) if ttl_override and ttl_override >= 30 else 240.0,
            lead_s=45.0,
            ping_cap=2,
            guaranteed=False,
        )

    # 4. xAI / Grok
    if name in {"xai"} or backend == "xai_grok" or "grok" in model_lower:
        return CacheTtlPolicy(
            ttl_s=float(ttl_override) if ttl_override and ttl_override >= 30 else 240.0,
            lead_s=45.0,
            ping_cap=2,
            guaranteed=False,
        )

    return None
