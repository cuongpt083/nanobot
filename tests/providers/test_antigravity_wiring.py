"""Tests for Antigravity registry/config/factory wiring."""

from __future__ import annotations

import pytest

from nanobot.config.schema import Config, ProviderConfig, ProvidersConfig
from nanobot.providers.antigravity_provider import AntigravityProvider
from nanobot.providers.factory import make_provider


@pytest.fixture(autouse=True)
def _antigravity_client_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep factory-built adapters off the local credential discovery path."""

    monkeypatch.setenv("NANOBOT_ANTIGRAVITY_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("NANOBOT_ANTIGRAVITY_CLIENT_SECRET", "test-client-secret")


def test_registry_spec() -> None:
    from nanobot.providers.registry import find_by_name

    spec = find_by_name("google-antigravity")
    assert spec is not None
    assert spec.is_oauth is True
    assert spec.backend == "antigravity"
    assert spec.default_api_base == "https://daily-cloudcode-pa.googleapis.com"
    assert "google-antigravity" in {m.id.split("/", 1)[0] for m in spec.builtin_models}


def test_provider_config_parses_camel_case_antigravity() -> None:
    provider = ProviderConfig.model_validate(
        {
            "antigravity": {
                "enabled": True,
                "endpoint": "https://daily-cloudcode-pa.googleapis.com",
                "endpointFallbacks": ["https://cloudcode-pa.googleapis.com"],
                "userAgentVersion": "9.9.9",
                "callbackPort": 51121,
                "projectId": "proj",
            }
        }
    )
    assert provider.antigravity is not None
    assert provider.antigravity.user_agent_version == "9.9.9"
    assert provider.antigravity.project_id == "proj"
    assert provider.antigravity.endpoint_fallbacks == ["https://cloudcode-pa.googleapis.com"]


def test_providers_config_defaults() -> None:
    provider = ProvidersConfig().google_antigravity
    assert provider.antigravity is not None
    assert provider.antigravity.user_agent_version == "1.21.9"
    assert provider.antigravity.endpoint == "https://daily-cloudcode-pa.googleapis.com"


def test_factory_builds_antigravity_provider_without_api_key() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "model": "google-antigravity/gemini-3-pro-low",
                    "provider": "google_antigravity",
                }
            }
        }
    )
    provider = make_provider(config)
    assert isinstance(provider, AntigravityProvider)
    assert provider.get_default_model() == "google-antigravity/gemini-3-pro-low"
    assert provider.provider_name == "google_antigravity"


def test_factory_applies_antigravity_settings() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "google_antigravity": {
                    "antigravity": {"endpoint": "https://example.test", "userAgentVersion": "2.0.0"}
                }
            },
            "agents": {
                "defaults": {
                    "model": "google-antigravity/gemini-3-pro-low",
                    "provider": "google_antigravity",
                }
            },
        }
    )
    provider = make_provider(config)
    assert isinstance(provider, AntigravityProvider)
    assert provider._adapter.endpoint == "https://example.test"
    assert provider._adapter.user_agent_version == "2.0.0"


def test_factory_allows_proxy_for_antigravity() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "google_antigravity": {"proxy": "http://127.0.0.1:7890"}
            },
            "agents": {
                "defaults": {
                    "model": "google-antigravity/gemini-3-pro-low",
                    "provider": "google_antigravity",
                }
            },
        }
    )
    provider = make_provider(config)
    assert isinstance(provider, AntigravityProvider)
    assert provider._proxy == "http://127.0.0.1:7890"


def test_oauth_model_catalog_dispatch_registered() -> None:
    from nanobot.providers.oauth_model_catalog import invalidate_oauth_model_catalog

    # Must not raise "not available" for the Antigravity provider.
    invalidate_oauth_model_catalog("google_antigravity")


def test_adapter_version_floor_applied_by_factory() -> None:
    config = Config.model_validate(
        {
            "providers": {
                "google_antigravity": {"antigravity": {"userAgentVersion": "1.0.0"}}
            },
            "agents": {
                "defaults": {
                    "model": "google-antigravity/gemini-3-pro-low",
                    "provider": "google_antigravity",
                }
            },
        }
    )
    provider = make_provider(config)
    assert provider._adapter.user_agent_version == "1.21.9"


def test_cli_oauth_handlers_include_antigravity() -> None:
    from nanobot.cli.provider import (
        _LOGIN_HANDLERS,
        _LOGOUT_HANDLERS,
        _OAUTH_PROVIDER_DEFAULT_MODELS,
        _resolve_oauth_provider,
    )

    assert "google_antigravity" in _LOGIN_HANDLERS
    assert "google_antigravity" in _LOGOUT_HANDLERS
    assert _OAUTH_PROVIDER_DEFAULT_MODELS["google_antigravity"].startswith("google-antigravity/")
    assert _resolve_oauth_provider("google-antigravity").name == "google_antigravity"


def test_webui_oauth_status_reports_antigravity_not_configured(
    monkeypatch, tmp_path
) -> None:
    import nanobot.providers.antigravity_oauth as oauth_module
    from nanobot.providers.registry import find_by_name
    from nanobot.webui.settings_models import oauth_provider_status

    monkeypatch.setattr(
        oauth_module,
        "get_antigravity_oauth_storage_path",
        lambda: tmp_path / "missing.json",
    )
    status = oauth_provider_status(find_by_name("google-antigravity"))
    assert status["login_supported"] is True
    assert status["configured"] is False

