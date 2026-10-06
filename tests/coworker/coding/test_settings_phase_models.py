"""Per-phase Pi model configuration: payload, validation, and settings round-trip."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.coworker import settings_api
from nanobot.coworker.config import (
    CodingAgentConfig,
    CoworkerConfig,
    PiBackendConfig,
    PiPhaseConfig,
    PiPhases,
)
from nanobot.coworker.settings_api import (
    CoworkerSettingsError,
    _check_phase_models,
    coworker_phase_models_payload,
)

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")


def _cfg(phases: PiPhases) -> CoworkerConfig:
    return CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            repos=[],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                phases=phases,
            ),
        )
    )


def test_phase_models_payload_detect_false() -> None:
    payload = coworker_phase_models_payload(detect=False)
    assert payload["models"] == []
    assert "high" in payload["thinking_levels"]
    assert payload["error"] is None


def test_fetch_phase_models_from_pi() -> None:
    cfg = _cfg(PiPhases())
    with patch.object(settings_api, "load_coworker_config", return_value=cfg):
        payload = coworker_phase_models_payload(refresh=True)
    assert payload["error"] is None
    values = {m["value"] for m in payload["models"]}
    assert "fake/fake-model" in values
    assert "high" in payload["thinking_levels"]


def test_check_phase_models_rejects_bad_format() -> None:
    cfg = _cfg(PiPhases(plan=PiPhaseConfig(model="not-a-provider-model")))
    with pytest.raises(CoworkerSettingsError, match="provider/modelId"):
        _check_phase_models(cfg)


def test_check_phase_models_accepts_provider_slash_model() -> None:
    cfg = _cfg(PiPhases(review=PiPhaseConfig(model="anthropic/claude-sonnet", thinking="high")))
    _check_phase_models(cfg)  # must not raise (maybe returns a warning list)


def test_check_phase_models_no_warning_when_models_unset() -> None:
    assert _check_phase_models(_cfg(PiPhases())) == []


def test_check_phase_models_warns_when_review_matches_implement() -> None:
    cfg = _cfg(
        PiPhases(
            implement=PiPhaseConfig(model="fake/fake-model"),
            review=PiPhaseConfig(model="fake/fake-model"),
        )
    )
    warnings = _check_phase_models(cfg)
    assert any("matches implement.model" in w for w in warnings)


def test_settings_payload_includes_phases() -> None:
    cfg = _cfg(PiPhases())
    with patch.object(settings_api, "load_coworker_config", return_value=cfg):
        payload = settings_api.coworker_settings_payload([], detect=False)
    phases = payload["config"]["coding"]["pi"]["phases"]
    assert phases["plan"]["thinking"] == "high"
    assert phases["implement"]["thinking"] == "medium"
    assert phases["review"]["thinking"] == "high"
