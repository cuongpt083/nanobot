"""Classifying a project directory with git, and cutting worktrees from the repository root."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from nanobot.coworker.coding.tasks import CodingTask
from nanobot.coworker.coding.workspace import (
    WorkspaceError,
    WorkspaceManager,
    inspect_project,
)
from nanobot.coworker.config import CodingAgentConfig, RepoConfig


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path: Path, *, commit: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")
    if commit:
        (path / "README.md").write_text("# repo\n", encoding="utf-8")
        _git(path, "add", "README.md")
        _git(path, "commit", "-m", "init")
    return path


@pytest.mark.asyncio
async def test_repository_root(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    info = await inspect_project(repo)
    assert info.kind == "git"
    assert info.toplevel == repo.resolve()
    assert info.rel == ""
    assert info.has_worktree_support


@pytest.mark.asyncio
async def test_subdirectory_of_a_repository(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "mono")
    sub = repo / "packages" / "web"
    sub.mkdir(parents=True)
    info = await inspect_project(sub)
    assert info.kind == "git_subdir"
    assert info.toplevel == repo.resolve()
    assert info.rel == "packages/web"


@pytest.mark.asyncio
async def test_repository_without_commits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "fresh", commit=False)
    info = await inspect_project(repo)
    assert info.kind == "git_empty"
    assert not info.has_worktree_support


@pytest.mark.asyncio
async def test_plain_directory(tmp_path: Path) -> None:
    plain = tmp_path / "docs"
    plain.mkdir()
    info = await inspect_project(plain)
    assert info.kind == "non_git"
    assert info.toplevel is None


@pytest.mark.asyncio
async def test_path_with_spaces_and_unicode(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "Dự án có dấu cách")
    assert (await inspect_project(repo)).kind == "git"


@pytest.mark.asyncio
async def test_worktree_is_cut_from_the_root_for_a_subdirectory(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "mono")
    sub = repo / "packages" / "web"
    sub.mkdir(parents=True)
    (sub / "index.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "add web")

    cfg = CodingAgentConfig(enabled=True, repos=[])
    mgr = WorkspaceManager(cfg, tmp_path / "ws")
    repo_cfg = RepoConfig(path=str(sub))
    worktree, branch = await mgr.create_worktree(repo=repo_cfg, task_id="t1")
    try:
        assert (worktree / "README.md").exists()  # the worktree is the whole repository
        kind = await mgr.project_kind(repo_cfg)
        task = CodingTask(
            id="t1", backend="agy", session_key="s", channel="c", chat_id="u",
            repo=str(sub), base="HEAD", branch=branch, worktree=str(worktree), brief="b",
            subdir=kind.rel,
        )
        assert task.run_dir == worktree / "packages" / "web"
        assert (task.run_dir / "index.txt").exists()
        # merge/cleanup work from the root even though the project is a subdirectory
        await mgr.cleanup(repo=repo_cfg, task_id="t1", delete_branch=True)
        assert not worktree.exists()
    finally:
        subprocess.run(["git", "worktree", "prune"], cwd=repo, capture_output=True)


def test_run_dir_defaults_to_the_worktree() -> None:
    task = CodingTask(
        id="t", backend="pi", session_key="s", channel="c", chat_id="u",
        repo="/r", base="HEAD", branch="b", worktree="/w/t", brief="b",
    )
    assert task.run_dir == Path("/w/t")
    assert CodingTask.from_dict({k: v for k, v in task.to_dict().items() if k != "subdir"}).subdir == ""


@pytest.mark.asyncio
async def test_create_worktree_explains_why_it_cannot_run(tmp_path: Path) -> None:
    mgr = WorkspaceManager(CodingAgentConfig(enabled=True, repos=[]), tmp_path / "ws")
    plain = tmp_path / "docs"
    plain.mkdir()
    with pytest.raises(WorkspaceError, match="not inside a git repository"):
        await mgr.create_worktree(repo=RepoConfig(path=str(plain)), task_id="t2")
    fresh = _init_repo(tmp_path / "fresh", commit=False)
    with pytest.raises(WorkspaceError, match="without any commit"):
        await mgr.create_worktree(repo=RepoConfig(path=str(fresh)), task_id="t3")
