"""Tests for atomic config.json writes."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


def test_save_config_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    save_config(Config(), path)
    loaded = load_config(path)
    assert loaded.agents.defaults.model


def test_save_config_persists_anthropic_oauth_request_settings(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = Config()
    config.providers.anthropic_oauth.proxy = "http://127.0.0.1:7890"
    config.providers.anthropic_oauth.extra_headers = {"X-Test": "1"}

    save_config(config, path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["providers"]["anthropicOauth"]["proxy"] == "http://127.0.0.1:7890"
    assert raw["providers"]["anthropicOauth"]["extraHeaders"] == {"X-Test": "1"}

    loaded = load_config(path)
    assert loaded.providers.anthropic_oauth.proxy == "http://127.0.0.1:7890"
    assert loaded.providers.anthropic_oauth.extra_headers == {"X-Test": "1"}


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX file modes")
def test_save_config_preserves_existing_file_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)

    save_config(Config(), path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_config_preserves_existing_file_when_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.json"
    save_config(Config(), path)
    before = path.read_text(encoding="utf-8")

    def boom(self: Path, target: Path) -> Path:  # noqa: ARG001
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="simulated crash"):
        save_config(Config(), path)

    assert path.read_text(encoding="utf-8") == before
    assert json.loads(before)  # still valid JSON
