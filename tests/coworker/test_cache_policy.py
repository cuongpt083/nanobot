"""Tests for coworker cache_policy module."""

from __future__ import annotations

from types import SimpleNamespace

from nanobot.coworker.context import cache_policy


def test_anthropic_direct_policy() -> None:
    provider = SimpleNamespace(provider_name="anthropic", backend="anthropic")
    policy_short = cache_policy.resolve(provider, "claude-3-5-sonnet")
    assert policy_short is not None
    assert policy_short.ttl_s == 300.0
    assert policy_short.lead_s == 60.0
    assert policy_short.ping_cap == 6
    assert policy_short.guaranteed is True

    # Retention long
    policy_long = cache_policy.resolve(provider, "claude-3-5-sonnet", retention="long")
    assert policy_long is not None
    assert policy_long.ttl_s == 3600.0
    assert policy_long.guaranteed is True

    assert cache_policy.supports_ttl1h(provider) is True


def test_anthropic_indirect_claude_model() -> None:
    # Gateway/proxy routing claude
    provider = SimpleNamespace(provider_name="openrouter", backend="openai_compat")
    policy = cache_policy.resolve(provider, "anthropic/claude-3-7-sonnet")
    assert policy is not None
    assert policy.ttl_s == 300.0
    assert policy.guaranteed is False  # Not direct Anthropic
    assert cache_policy.supports_ttl1h(provider) is False


def test_openai_and_codex_policy() -> None:
    provider_codex = SimpleNamespace(provider_name="openai_codex", backend="openai_codex")
    policy_codex = cache_policy.resolve(provider_codex, "gpt-4o")
    assert policy_codex is not None
    assert policy_codex.ttl_s == 300.0
    assert policy_codex.lead_s == 60.0
    assert policy_codex.ping_cap == 4
    assert policy_codex.guaranteed is False
    assert cache_policy.supports_ttl1h(provider_codex) is False

    provider_openai = SimpleNamespace(provider_name="openai", backend="openai_compat")
    policy_o1 = cache_policy.resolve(provider_openai, "o1-mini")
    assert policy_o1 is not None
    assert policy_o1.ping_cap == 4


def test_gemini_and_antigravity_policy() -> None:
    provider = SimpleNamespace(provider_name="gemini", backend="openai_compat")
    policy = cache_policy.resolve(provider, "gemini-2.5-pro")
    assert policy is not None
    assert policy.ttl_s == 240.0
    assert policy.lead_s == 45.0
    assert policy.ping_cap == 2
    assert policy.guaranteed is False

    provider_agy = SimpleNamespace(provider_name="antigravity", backend="openai_compat")
    policy_agy = cache_policy.resolve(provider_agy, "gemini-2.5-flash")
    assert policy_agy is not None
    assert policy_agy.ttl_s == 240.0


def test_xai_grok_policy() -> None:
    provider = SimpleNamespace(provider_name="xai", backend="xai_grok")
    policy = cache_policy.resolve(provider, "grok-beta")
    assert policy is not None
    assert policy.ttl_s == 240.0
    assert policy.lead_s == 45.0
    assert policy.ping_cap == 2


def test_unknown_provider_returns_none() -> None:
    provider = SimpleNamespace(provider_name="custom_local", backend="openai_compat")
    policy = cache_policy.resolve(provider, "my-local-llama-7b")
    assert policy is None


def test_ttl_override() -> None:
    provider = SimpleNamespace(provider_name="openai", backend="openai_compat")
    policy = cache_policy.resolve(provider, "gpt-4o", ttl_override=600)
    assert policy is not None
    assert policy.ttl_s == 600.0
