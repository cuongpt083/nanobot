"""Blocked project paths and outside-write detection (cross-platform)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from nanobot.coworker.coding import guard
from nanobot.coworker.coding.guard import WriteWatch, blocked_reason


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home" / "me"
    home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    # tmp_path itself is under the temp dir, which is exempt; point temp elsewhere for these tests.
    monkeypatch.setattr(guard.tempfile, "gettempdir", lambda: str(tmp_path / "scratch"))
    return home


def test_root_home_and_home_parents_are_blocked(fake_home: Path) -> None:
    assert "root" in (blocked_reason(Path(fake_home.anchor)) or "")
    assert blocked_reason(fake_home)
    assert blocked_reason(fake_home.parent)


def test_project_subfolder_of_home_is_allowed(fake_home: Path) -> None:
    project = fake_home / "temp"
    project.mkdir()
    assert blocked_reason(project) is None


@pytest.mark.parametrize("name", [".ssh", ".aws", ".config", "AppData", "Library"])
def test_credential_and_tool_dirs_in_home_are_blocked(fake_home: Path, name: str) -> None:
    target = fake_home / name / "proj"
    target.mkdir(parents=True)
    assert blocked_reason(target)
    assert blocked_reason(fake_home / name)


def test_system_directories_are_blocked() -> None:
    if os.name == "nt":
        root = os.environ.get("SystemRoot")
        assert root and blocked_reason(root)
    else:
        assert blocked_reason("/etc")
        assert blocked_reason("/usr/local")


def test_symlink_into_a_blocked_dir_is_resolved(fake_home: Path, tmp_path: Path) -> None:
    secret = fake_home / ".ssh"
    secret.mkdir()
    link = fake_home / "innocent"
    try:
        link.symlink_to(secret, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    assert blocked_reason(link)


def test_temp_dir_is_exempt(tmp_path: Path) -> None:
    assert blocked_reason(tmp_path / "proj") is None


def test_user_blocked_paths(tmp_path: Path) -> None:
    blocked = tmp_path / "company-secrets"
    (blocked / "sub").mkdir(parents=True)
    assert blocked_reason(blocked / "sub", [str(blocked)])
    assert blocked_reason(tmp_path / "other", [str(blocked)]) is None


def _touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    future = time.time() + 5  # guarantee a different mtime on coarse-grained filesystems
    os.utime(path, (future, future))


def test_direct_mode_reports_sibling_and_credential_writes(fake_home: Path, tmp_path: Path) -> None:
    project = tmp_path / "work" / "proj"
    project.mkdir(parents=True)
    _touch(tmp_path / "work" / "neighbour.txt", "a")
    _touch(fake_home / ".bashrc", "a")

    watch = WriteWatch(project, project, direct=True)
    _touch(project / "inside.py")  # sanctioned: must not be reported
    _touch(tmp_path / "work" / "neighbour.txt", "changed!")
    _touch(tmp_path / "work" / "new.txt")
    _touch(fake_home / ".bashrc", "evil")
    _touch(fake_home / ".ssh" / "authorized_keys")

    report = watch.check()
    flat = " ".join(report.lines())
    assert "inside.py" not in flat
    assert "neighbour.txt" in flat and "new.txt" in flat
    assert ".bashrc" in flat and "authorized_keys" in flat
    crit = " ".join(report.critical)
    assert ".bashrc" in crit and "authorized_keys" in crit and "neighbour.txt" not in crit


def test_worktree_mode_reports_base_checkout_and_git_hooks(fake_home: Path, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    _touch(repo / "app.py", "v1")
    worktree = tmp_path / "wt"
    worktree.mkdir()

    watch = WriteWatch(worktree, repo, direct=False)
    _touch(worktree / "app.py", "ok")  # the worktree is the sanctioned target
    _touch(repo / "app.py", "tampered")
    _touch(repo / ".git" / "hooks" / "pre-commit", "#!/bin/sh")

    report = watch.check()
    flat = " ".join(report.lines())
    assert "app.py" in flat and "pre-commit" in flat
    crit = " ".join(report.critical)
    assert "pre-commit" in crit and "app.py" not in crit


def test_no_changes_no_report(fake_home: Path, tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    assert not WriteWatch(project, project, direct=True).check()
