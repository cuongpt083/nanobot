from __future__ import annotations

from typing import Any

from nanobot.config.schema import Config, ProviderConfig
from nanobot.webui.settings_capabilities import (
    capability_settings_payload,
    update_api_settings,
    update_image_generation_settings,
    update_network_safety_settings,
    update_transcription_settings,
    update_web_search_settings,
)
from nanobot.webui.settings_contracts import WebUISettingsError


def _oauth_status(_spec: Any) -> dict[str, Any]:
    return {"configured": False}


def test_capability_domain_updates_representative_settings() -> None:
    config = Config()
    config.providers.openrouter.api_key = "sk-test"

    web_changed, web_restart = update_web_search_settings(
        config,
        {
            "provider": ["duckduckgo"],
            "max_results": ["7"],
            "use_jina_reader": ["false"],
        },
    )
    update_api_settings(
        config,
        {"host": ["127.0.0.2"], "port": ["8900"], "timeout": ["90"]},
    )
    image_changed = update_image_generation_settings(
        config,
        {"enabled": ["true"], "provider": ["openrouter"]},
        oauth_status=_oauth_status,
    )
    transcription_changed = update_transcription_settings(
        config,
        {"provider": ["openrouter"], "model": ["openai/whisper-large-v3"]},
    )
    network_changed, access_mode = update_network_safety_settings(
        config,
        {
            "webui_allow_local_service_access": ["false"],
            "webui_default_access_mode": ["restricted"],
        },
    )
    payload = capability_settings_payload(config, oauth_status=_oauth_status)

    assert (web_changed, web_restart) == (True, True)
    assert image_changed is True
    assert transcription_changed is True
    assert (network_changed, access_mode) == (True, "default")
    assert payload["web_search"]["max_results"] == 7
    assert payload["api"]["host"] == "127.0.0.2"
    assert payload["api"]["port"] == 8900
    assert payload["image_generation"]["enabled"] is True
    assert payload["transcription"]["provider"] == "openrouter"


def test_image_generation_provider_rows_and_update_custom_providers() -> None:
    config = Config.model_validate({
        "providers": {
            "custom-agy-17": {
                "apiBase": "http://192.168.100.17:8000/v1",
                "displayName": "Agy 17 Gateway",
            },
            "custom-unconfigured": {},
        },
    })
    assert isinstance(config.providers.model_extra["custom-agy-17"], ProviderConfig)

    payload = capability_settings_payload(config, oauth_status=_oauth_status)
    image_rows = {row["name"]: row for row in payload["image_generation"]["providers"]}

    assert "custom" in image_rows
    assert image_rows["custom"]["models"] is None

    assert "custom-agy-17" in image_rows
    agy_row = image_rows["custom-agy-17"]
    assert agy_row["label"] == "Agy 17 Gateway"
    assert agy_row["configured"] is True
    assert agy_row["api_base"] == "http://192.168.100.17:8000/v1"
    assert agy_row["models"] is None

    assert "custom-unconfigured" in image_rows
    assert image_rows["custom-unconfigured"]["configured"] is False

    # Update succeeds with configured custom provider
    changed = update_image_generation_settings(
        config,
        {"enabled": ["true"], "provider": ["custom-agy-17"], "model": ["gemini-3.8-flash-high"]},
        oauth_status=_oauth_status,
    )
    assert changed is True
    assert config.tools.image_generation.provider == "custom-agy-17"
    assert config.tools.image_generation.model == "gemini-3.8-flash-high"

    # Update fails if provider is unconfigured
    try:
        update_image_generation_settings(
            config,
            {"enabled": ["true"], "provider": ["custom-unconfigured"]},
            oauth_status=_oauth_status,
        )
        assert False, "expected WebUISettingsError for unconfigured custom provider"
    except WebUISettingsError as exc:
        assert "not configured" in str(exc)

    # Update fails if custom provider does not exist in config
    try:
        update_image_generation_settings(
            config,
            {"enabled": ["true"], "provider": ["custom-nonexistent"]},
            oauth_status=_oauth_status,
        )
        assert False, "expected WebUISettingsError for nonexistent custom provider"
    except WebUISettingsError as exc:
        assert "unknown image generation provider" in str(exc)
