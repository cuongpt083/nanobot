"""Project resolution for coding tasks: user-chosen directory, allowlist, trust boundary."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nanobot.coworker.coding.project import ProjectError, resolve_project
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.workspace import WorkspaceManager
from nanobot.coworker.config import CodingAgentConfig, CoworkerConfig, RepoConfig
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY


def _session(project: Path | str | None) -> SimpleNamespace:
    meta: dict[str, object] = {}
    if project is not None:
        meta[WORKSPACE_SCOPE_METADATA_KEY] = {
            "project_path": str(project),
            "access_mode": "restricted",
        }
    return SimpleNamespace(metadata=meta)


def _cfg(*repos: RepoConfig) -> CodingAgentConfig:
    return CodingAgentConfig(enabled=True, repos=list(repos))


def test_session_project_wins_and_needs_no_repos(tmp_path: Path) -> None:
    target = resolve_project(_session(tmp_path), _cfg())
    assert target.source == "scope"
    assert target.path == tmp_path.resolve()
    assert target.profile is None
    assert target.repo_config.path == str(tmp_path.resolve())
    assert target.repo_config.base_ref == "HEAD"


def test_scope_beats_the_single_configured_repo(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    target = resolve_project(_session(chosen), _cfg(RepoConfig(path=str(other))))
    assert target.path == chosen.resolve()


def test_profile_applies_defaults_when_path_matches(tmp_path: Path) -> None:
    profile = RepoConfig(path=str(tmp_path), acceptance="pytest -q", base_ref="main", backend="pi")
    target = resolve_project(_session(tmp_path), _cfg(profile))
    assert target.profile is profile
    assert target.repo_config.acceptance == "pytest -q"
    assert target.repo_config.base_ref == "main"
    assert target.repo_config.backend == "pi"


def test_no_scope_single_repo_is_used(tmp_path: Path) -> None:
    repo = RepoConfig(path=str(tmp_path))
    target = resolve_project(_session(None), _cfg(repo))
    assert target.source == "config"
    assert target.profile is repo


def test_no_scope_no_repos_is_refused() -> None:
    with pytest.raises(ProjectError, match="No repositories configured"):
        resolve_project(_session(None), _cfg())
    with pytest.raises(ProjectError, match="No repositories configured"):
        resolve_project(None, _cfg())


def test_no_scope_many_repos_is_ambiguous(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    with pytest.raises(ValueError, match="Ambiguous"):
        resolve_project(None, _cfg(RepoConfig(path=str(a)), RepoConfig(path=str(b))))


def test_model_supplied_repo_outside_the_allowed_set_is_rejected(tmp_path: Path) -> None:
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    evil = tmp_path / "evil"
    evil.mkdir()
    with pytest.raises(ProjectError, match="not allowed"):
        resolve_project(_session(chosen), _cfg(), str(evil))
    with pytest.raises(ProjectError, match="not allowed"):
        resolve_project(None, _cfg(), str(evil))


def test_model_supplied_repo_equal_to_scope_or_config_is_accepted(tmp_path: Path) -> None:
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    listed = tmp_path / "listed"
    listed.mkdir()
    cfg = _cfg(RepoConfig(path=str(listed), acceptance="make test"))
    assert resolve_project(_session(chosen), cfg, str(chosen)).source == "scope"
    via_config = resolve_project(_session(chosen), cfg, str(listed))
    assert via_config.source == "config"
    assert via_config.repo_config.acceptance == "make test"


def test_stale_scope_directory_is_an_error_not_a_silent_fallback(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    with pytest.raises(ProjectError, match="no longer usable"):
        resolve_project(_session(gone), _cfg(RepoConfig(path=str(tmp_path))))


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive paths are a Windows concern")
def test_windows_paths_compare_case_insensitively(tmp_path: Path) -> None:
    chosen = tmp_path / "Chosen"
    chosen.mkdir()
    target = resolve_project(_session(chosen), _cfg(), str(chosen).upper())
    assert target.source == "scope"


def test_admit_uses_session_project_without_configured_repos(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    cfg = CoworkerConfig(coding=CodingAgentConfig(enabled=True, repos=[]))
    runner = CodingRunner(cfg, tmp_path / "ws")
    with (
        patch("nanobot.coworker.coding.runner._lookup_session", return_value=_session(project)),
        patch("nanobot.coworker.coding.runner.shutil.which", return_value="/bin/agy"),
    ):
        task, _backend, repo = runner.admit(
            brief="b", session_key="s-scope", channel="c", chat_id="u", backend_name="agy"
        )
    assert task.repo == str(project.resolve())
    assert repo.path == str(project.resolve())


def test_admit_rejects_model_supplied_repo(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    cfg = CoworkerConfig(coding=CodingAgentConfig(enabled=True, repos=[]))
    runner = CodingRunner(cfg, tmp_path / "ws")
    with patch("nanobot.coworker.coding.runner._lookup_session", return_value=_session(project)):
        with pytest.raises(ProjectError, match="not allowed"):
            runner.admit(
                brief="b",
                session_key="s-evil",
                channel="c",
                chat_id="u",
                repo_path=str(tmp_path / "elsewhere"),
            )


def test_validate_task_repo_trusts_admitted_task_and_uses_profile(tmp_path: Path) -> None:
    listed = tmp_path / "listed"
    listed.mkdir()
    unlisted = tmp_path / "unlisted"
    unlisted.mkdir()
    cfg = _cfg(RepoConfig(path=str(listed), base_ref="main"))
    mgr = WorkspaceManager(cfg, tmp_path / "ws")
    assert mgr.validate_task_repo(listed).base_ref == "main"
    assert mgr.validate_task_repo(unlisted).path == str(unlisted)
    # The strict allowlist check is unchanged for everything else.
    from nanobot.coworker.coding.workspace import WorkspaceError

    with pytest.raises(WorkspaceError):
        mgr.validate_repo(unlisted)
