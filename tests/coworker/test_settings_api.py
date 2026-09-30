"""WebUI Coworker settings backend: validation, atomic write, key preservation, detection."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from nanobot.coworker import settings_api
from nanobot.coworker.config import (
    coworker_config_path,
    invalidate_coworker_config_cache,
    load_coworker_config,
    set_coworker_config_override,
)
from nanobot.coworker.settings_api import CoworkerSettingsError, update_coworker_settings

PRESETS = ["fast", "strong"]


@pytest.fixture
def cfg_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "coworker.json"
    monkeypatch.setenv("NANOBOT_COWORKER_CONFIG", str(path))
    set_coworker_config_override(None)
    invalidate_coworker_config_cache()
    yield path
    invalidate_coworker_config_cache()


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    return path


def test_payload_defaults_list_sections_presets_and_detection(cfg_file: Path) -> None:
    payload = settings_api.coworker_settings_payload(PRESETS)
    assert set(payload["config"]) == {"advisor", "room", "coding"}
    assert payload["config"]["advisor"]["max_uses"] == 10
    assert payload["presets"] == ["default", "fast", "strong"]
    assert set(payload["detection"]) == {"pi", "agy"}
    assert payload["repos"] == [] and payload["path"] == str(cfg_file)


def test_update_writes_camel_case_and_hot_reloads(cfg_file: Path) -> None:
    payload = update_coworker_settings(
        {"advisor": {"preset": "strong", "max_uses": 4, "review_nudge": False}}, PRESETS, detect=False
    )
    assert payload["config"]["advisor"]["preset"] == "strong"
    written = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert written["advisor"]["maxUses"] == 4 and written["advisor"]["reviewNudge"] is False
    assert "max_uses" not in written["advisor"]
    live = load_coworker_config()
    assert live.advisor.preset == "strong" and live.advisor.max_uses == 4
    assert not list(cfg_file.parent.glob("*.tmp"))


def test_update_preserves_other_sections_and_unknown_keys(cfg_file: Path) -> None:
    cfg_file.write_text(json.dumps({
        "context": {"optimize": True},
        "advisor": {"maxUses": 3, "futureKey": {"a": 1}},
        "topLevelFuture": 1,
    }), encoding="utf-8")
    update_coworker_settings({"advisor": {"preset": "fast"}}, PRESETS, detect=False)
    written = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert written["context"] == {"optimize": True}
    assert written["topLevelFuture"] == 1
    assert written["advisor"]["futureKey"] == {"a": 1}
    assert written["advisor"]["preset"] == "fast"


def test_invalid_existing_file_is_never_overwritten(cfg_file: Path) -> None:
    cfg_file.write_text("{ not json", encoding="utf-8")
    with pytest.raises(CoworkerSettingsError) as err:
        update_coworker_settings({"advisor": {"preset": "fast"}}, PRESETS, detect=False)
    assert err.value.status == 409
    assert cfg_file.read_text(encoding="utf-8") == "{ not json"


@pytest.mark.parametrize(
    ("values", "needle"),
    [
        ({"advisor": {"max_uses": 0}}, "advisor"),
        ({"advisor": {"preset": "nope"}}, "advisor.preset: unknown model preset"),
        ({"room": {"agents": [{"id": "Bad Id!"}]}}, "room"),
        ({"room": {"agents": [{"id": "a"}, {"id": "a"}]}}, "duplicate agent id"),
        ({"room": {"agents": [{"id": "a", "preset": "nope"}]}}, "room.agents[0].preset"),
        ({"coding": {"agy": {"extra_args": ["--model=x"]}}}, "disallowed flag"),
        ({"coding": {"pi": {"pass_env": ["ANTHROPIC_API_KEY"]}}}, "looks like a credential"),
        ({"coding": {"pi": {"pass_env": ["not a name"]}}}, "not a variable name"),
        ({"context": {"optimize": True}}, "unknown section"),
        ({}, "nothing to update"),
        ({"advisor": "x"}, "must be an object"),
    ],
)
def test_invalid_submissions_are_rejected_without_writing(cfg_file: Path, values: dict, needle: str) -> None:
    with pytest.raises(CoworkerSettingsError) as err:
        update_coworker_settings(values, PRESETS, detect=False)
    assert needle in err.value.message
    assert not cfg_file.exists()


def test_advisor_off_is_a_valid_preset(cfg_file: Path) -> None:
    update_coworker_settings({"advisor": {"preset": "off"}}, PRESETS, detect=False)
    assert load_coworker_config().advisor.preset == "off"


def test_repos_must_be_absolute_existing_git_repositories(cfg_file: Path, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    repo = _git_repo(tmp_path / "repo")
    bad = [
        ({"coding": {"repos": [{"path": "relative/dir"}]}}, "must be absolute"),
        ({"coding": {"repos": [{"path": str(tmp_path / "missing")}]}}, "directory not found"),
        ({"coding": {"repos": [{"path": str(plain)}]}}, "not a git repository"),
        ({"coding": {"repos": [{"path": str(repo)}, {"path": str(repo)}]}}, "duplicate repository"),
    ]
    for values, needle in bad:
        with pytest.raises(CoworkerSettingsError) as err:
            update_coworker_settings(values, PRESETS, detect=False)
        assert needle in err.value.message
    assert not cfg_file.exists()

    payload = update_coworker_settings(
        {"coding": {"enabled": True, "repos": [{"path": str(repo), "acceptance": "pytest -q", "backend": "pi"}]}},
        PRESETS,
        detect=False,
    )
    assert payload["repos"][0]["ok"] is True and payload["repos"][0]["branch"] == "main"
    reloaded = load_coworker_config().coding
    assert reloaded.enabled and reloaded.repos[0].acceptance == "pytest -q"


def test_detection_never_executes_custom_commands(tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    script = tmp_path / "fake.py"
    script.write_text(f"open({str(marker)!r}, 'w').write('x')\n", encoding="utf-8")
    found = settings_api.detect_backend("pi", [sys.executable, str(script)])
    assert found["found"] is True and found["custom"] is True and found["version"] is None
    assert not marker.exists()

    missing = settings_api.detect_backend("agy", ["definitely-not-installed-agy"])
    assert missing["found"] is False and missing["path"] is None


def test_config_path_follows_the_environment_override(cfg_file: Path) -> None:
    assert coworker_config_path() == cfg_file
