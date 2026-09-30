"""Tests for Anthropic OAuth patcher wiring through config and factory."""

from __future__ import annotations

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

    from nanobot.providers.patcher.rules import PatcherConfig

    provider = AnthropicProvider(
        auth_mode="oauth",
        patcher_config=PatcherConfig(enabled=True, port=port, rules=[]),
    )
    await provider._ensure_patcher_started()
    assert provider._patcher_proxy is not None
    assert provider._patcher_proxy.is_running
    assert provider._patcher_proxy.port == port
    await provider.aclose()
    assert provider._patcher_proxy is None
