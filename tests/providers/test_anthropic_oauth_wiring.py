"""Tests for Anthropic OAuth patcher wiring through config and factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from nanobot.config.schema import Config, ProviderConfig
from nanobot.providers.anthropic_provider import AnthropicProvider
from nanobot.providers.factory import make_provider


def test_provider_config_parses_camel_case_patcher() -> None:
    provider = ProviderConfig.model_validate(
        {
            "authMode": "oauth",
            "patcher": {
                "enabled": True,
                "port": 18793,
                "targetBaseUrl": "https://api.anthropic.com",
                "claudeCodeVersion": "2.1.280",
                "addSessionId": True,
            },
        }
    )
    assert provider.auth_mode == "oauth"
    assert provider.patcher is not None
    assert provider.patcher.enabled is True
    assert provider.patcher.port == 18793


def test_provider_config_defaults_to_api_key_without_patcher() -> None:
    provider = ProviderConfig()
    assert provider.auth_mode == "api_key"
    assert provider.patcher is None


def test_factory_builds_anthropic_oauth_provider_with_patcher() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "anthropic": {
                    "authMode": "oauth",
                    "patcher": {"enabled": True, "port": 19001},
                }
            },
            "agents": {
                "defaults": {
                    "model": "anthropic/claude-sonnet-4-6",
                    "provider": "anthropic",
                }
            },
        }
    )
    provider = make_provider(config)
    assert isinstance(provider, AnthropicProvider)
    assert provider._auth_mode == "oauth"
    assert provider._patcher_config is not None
    assert provider._patcher_config.enabled is True
    assert provider._patcher_config.port == 19001
    assert str(provider._client.base_url).startswith("http://127.0.0.1:19001")


def test_factory_builds_plain_api_key_anthropic_provider() -> None:
    config = Config.model_validate(
        {
            "providers": {"anthropic": {"apiKey": "sk-ant-test"}},
            "agents": {
                "defaults": {
                    "model": "anthropic/claude-sonnet-4-6",
                    "provider": "anthropic",
                }
            },
        }
    )
    provider = make_provider(config)
    assert isinstance(provider, AnthropicProvider)
    assert provider._auth_mode == "api_key"
    assert provider._patcher_config is None
    assert "api.anthropic.com" in str(provider._client.base_url)

async def test_ensure_patcher_started_binds_configured_port() -> None:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    from nanobot.providers.patcher.proxy import stop_anthropic_patcher_proxy
    from nanobot.providers.patcher.rules import PatcherConfig

    provider = AnthropicProvider(
        auth_mode="oauth",
        patcher_config=PatcherConfig(enabled=True, port=port, rules=[]),
    )
    await provider._ensure_patcher_started()
    assert provider._patcher_proxy is not None
    assert provider._patcher_proxy.is_running
    assert provider._patcher_proxy.port == port
    assert str(provider._client.base_url).startswith(f"http://127.0.0.1:{port}")
    await provider.aclose()
    assert provider._patcher_proxy is None
    # The proxy is process-wide; shutting it down is the runtime's job.
    await stop_anthropic_patcher_proxy()


async def test_patcher_proxy_is_shared_across_providers() -> None:
    import socket

    from nanobot.providers.patcher.proxy import stop_anthropic_patcher_proxy
    from nanobot.providers.patcher.rules import PatcherConfig

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    config = PatcherConfig(enabled=True, port=port, rules=[])
    first = AnthropicProvider(auth_mode="oauth", patcher_config=config)
    second = AnthropicProvider(auth_mode="oauth", patcher_config=config)
    try:
        # Both providers must share one listener instead of racing the port.
        await first._ensure_patcher_started()
        await second._ensure_patcher_started()
        assert first._patcher_proxy is second._patcher_proxy
        assert first._patcher_proxy is not None
        assert first._patcher_proxy.port == port
    finally:
        await stop_anthropic_patcher_proxy()


def test_factory_wires_anthropic_proxy_into_patcher() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "anthropic": {
                    "authMode": "oauth",
                    "proxy": "http://127.0.0.1:7890",
                    "patcher": {"enabled": True},
                }
            },
            "agents": {
                "defaults": {
                    "model": "anthropic/claude-sonnet-4-6",
                    "provider": "anthropic",
                }
            },
        }
    )
    provider = make_provider(config)
    assert isinstance(provider, AnthropicProvider)
    assert provider._patcher_config is not None
    # The patcher's upstream connection carries the proxy setting.
    assert provider._patcher_config.proxy == "http://127.0.0.1:7890"


def test_factory_allows_proxy_for_api_key_anthropic() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "anthropic": {
                    "apiKey": "sk-ant-test",
                    "proxy": "http://127.0.0.1:7890",
                }
            },
            "agents": {
                "defaults": {
                    "model": "anthropic/claude-sonnet-4-6",
                    "provider": "anthropic",
                }
            },
        }
    )
    provider = make_provider(config)
    assert isinstance(provider, AnthropicProvider)
    assert provider._proxy == "http://127.0.0.1:7890"


def test_anthropic_oauth_registry_spec() -> None:
    from nanobot.providers.registry import find_by_name

    spec = find_by_name("anthropic-oauth")
    assert spec is not None
    assert spec.is_oauth is True
    assert spec.backend == "anthropic"
    assert spec.default_api_base == "https://api.anthropic.com"
    assert "anthropic-oauth" in {m.id.split("/", 1)[0] for m in spec.builtin_models}


def test_anthropic_oauth_provider_config_defaults_to_oauth_and_patcher() -> None:
    from nanobot.config.schema import ProvidersConfig

    provider = ProvidersConfig().anthropic_oauth
    assert provider.auth_mode == "oauth"
    assert provider.patcher is not None
    assert provider.patcher.enabled is True


def test_factory_builds_provider_from_anthropic_oauth_name() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "model": "anthropic-oauth/claude-sonnet-4-6",
                    "provider": "anthropic_oauth",
                }
            }
        }
    )
    provider = make_provider(config)
    assert isinstance(provider, AnthropicProvider)
    assert provider._auth_mode == "oauth"
    assert provider._patcher_config is not None
    assert provider._patcher_config.enabled is True


def test_cli_oauth_handlers_include_anthropic() -> None:
    from nanobot.cli.provider import (
        _LOGIN_HANDLERS,
        _LOGOUT_HANDLERS,
        _OAUTH_PROVIDER_DEFAULT_MODELS,
        _resolve_oauth_provider,
    )

    assert "anthropic_oauth" in _LOGIN_HANDLERS
    assert "anthropic_oauth" in _LOGOUT_HANDLERS
    assert _OAUTH_PROVIDER_DEFAULT_MODELS["anthropic_oauth"].startswith("anthropic-oauth/")
    assert _resolve_oauth_provider("anthropic-oauth").name == "anthropic_oauth"


def test_webui_oauth_status_reports_anthropic_not_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import nanobot.providers.anthropic_oauth as oauth_module
    from nanobot.providers.registry import find_by_name
    from nanobot.webui.settings_models import oauth_provider_status

    monkeypatch.setattr(
        oauth_module,
        "get_anthropic_oauth_storage_path",
        lambda: tmp_path / "missing.json",
    )
    status = oauth_provider_status(find_by_name("anthropic-oauth"))
    assert status["login_supported"] is True
    assert status["configured"] is False


def test_default_oauth_patcher_config_resolves_env_vars() -> None:
    """The default attribution template must not look like a ${VAR} reference."""
    from nanobot.config.loader import resolve_config_env_vars

    resolved = resolve_config_env_vars(Config.model_validate({}))
    patcher = resolved.providers.anthropic_oauth.patcher
    assert patcher is not None
    assert "{{version}}" in patcher.attribution_template


def test_anthropic_provider_maps_reauth_cause_to_oauth_auth_required() -> None:
    from nanobot.providers.anthropic_oauth import AnthropicOAuthReauthRequiredError
    from nanobot.providers.anthropic_provider import AnthropicProvider

    class _FakeSDKConnectionError(Exception):
        pass

    def _raise() -> None:
        try:
            raise AnthropicOAuthReauthRequiredError("expired")
        except AnthropicOAuthReauthRequiredError as cause:
            # The SDK wraps the credentials failure as a generic connection error.
            raise _FakeSDKConnectionError("Connection error.") from cause

    try:
        _raise()
    except _FakeSDKConnectionError as outgoing:
        response = AnthropicProvider._handle_error(outgoing)

    assert response.error_kind == "oauth_auth_required"
    assert response.error_should_retry is False
    assert "sign in again" in (response.content or "")


def test_anthropic_oauth_strips_provider_prefix_from_wire_model() -> None:
    from nanobot.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(
        api_key="sk-test",
        default_model="claude-opus-5-5",
        provider_name="anthropic_oauth",
    )

    assert provider._strip_prefix("anthropic-oauth/claude-opus-5-5") == "claude-opus-5-5"
    assert provider._strip_prefix("claude-opus-5-5") == "claude-opus-5-5"
    kwargs = provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model="anthropic-oauth/claude-opus-5-5",
        max_tokens=16,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )
    assert kwargs["model"] == "claude-opus-5-5"


def test_anthropic_provider_still_strips_legacy_anthropic_prefix() -> None:
    from nanobot.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(
        api_key="sk-test",
        default_model="claude-sonnet-4-6",
        provider_name="anthropic",
    )
    assert provider._strip_prefix("anthropic/claude-sonnet-4-6") == "claude-sonnet-4-6"
    # A vendor path that is not this provider's prefix is left untouched.
    assert provider._strip_prefix("vendor/model") == "vendor/model"
