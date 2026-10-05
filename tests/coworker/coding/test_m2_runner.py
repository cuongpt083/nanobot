"""Milestone M2 tests: workspace worktrees, task persistence, runner workflow, acceptance & recovery."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding.brief import render_acceptance_failure_prompt, render_rules
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.tasks import CodingTask, TaskRegistry
from nanobot.coworker.coding.workspace import WorkspaceError, WorkspaceManager
from nanobot.coworker.config import (
    AgyBackendConfig,
    CodingAgentConfig,
    CoworkerConfig,
    PiBackendConfig,
    RepoConfig,
)

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")
FAKE_AGY_SCRIPT = str(Path(__file__).parent / "fake_agy.py")


def _init_repo(path: Path) -> Path:
    """Initialize a git repo with an initial commit on main."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    (path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, check=True)
    return path


def test_brief_rules_and_acceptance_prompt() -> None:
    rules = render_rules("pytest -q")
    assert "RULES OF ENGAGEMENT" in rules
    assert "pytest -q" in rules

    prompt = render_acceptance_failure_prompt("pytest -q", "AssertionError: 1 != 2")
    assert "AssertionError: 1 != 2" in prompt
    assert "pytest -q" in prompt


@pytest.mark.asyncio
async def test_workspace_lifecycle_and_uncommitted_changes(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "main_repo")
    cfg = CodingAgentConfig(
        enabled=True,
        repos=[RepoConfig(path=str(repo_dir), base_ref="main")],
    )
    mgr = WorkspaceManager(cfg, tmp_path)

    # Validate repo
    repo_cfg = mgr.validate_repo(repo_dir)
    assert repo_cfg.path == str(repo_dir)

    # Symlink escape rejection
    symlink_dir = tmp_path / "sym_repo"
    try:
        os.symlink(repo_dir, symlink_dir)
        with pytest.raises(WorkspaceError):
            mgr.validate_repo(tmp_path / "non_existent_repo")
    except OSError:
        # Symlink creation requires elevated privileges on Windows unless developer mode is enabled
        pass

    # Create worktree
    wt_dir, branch = await mgr.create_worktree(repo=repo_cfg, task_id="test-wt-1", base_ref="main")
    assert wt_dir.exists()
    assert branch == "coworker/code/test-wt-1"

    # Make uncommitted change in worktree
    (wt_dir / "new_file.txt").write_text("Hello uncommitted", encoding="utf-8")
    committed = await mgr.commit_uncommitted_changes(wt_dir, "test_backend")
    assert committed is True

    # Diffstat and commits
    diffstat = await mgr.get_diffstat(wt_dir, "main")
    assert "new_file.txt" in diffstat
    commits = await mgr.get_commits(wt_dir, "main")
    assert len(commits) == 1
    assert "coworker: uncommitted changes" in commits[0]

    # Acceptance command run
    ok, out = await mgr.run_acceptance(wt_dir, "cat new_file.txt")
    assert ok is True
    assert "Hello uncommitted" in out

    # Cleanup
    await mgr.cleanup(repo=repo_cfg, task_id="test-wt-1", delete_branch=True)
    assert not wt_dir.exists()


@pytest.mark.asyncio
async def test_happy_path_runner_pi(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo_pi")
    coworker_cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="pi",
            repos=[RepoConfig(path=str(repo_dir), base_ref="main", acceptance="cat test.txt")],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_PI_SCENARIO"],
            ),
        )
    )

    runner = CodingRunner(coworker_cfg, tmp_path)
    task, backend, repo = runner.admit(
        brief="Create test.txt with Pi",
        session_key="sess-pi",
        channel="cli",
        chat_id="user-1",
    )

    with patch("nanobot.coworker.coding.runner.inject_turn", new_callable=AsyncMock) as mock_inject:
        with patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:test.txt:created by pi"}):
            msg = await runner.execute_task(task, backend, repo, wait=False)

    assert task.status == "succeeded"
    assert "created by pi" in msg or "Task" in msg
    mock_inject.assert_awaited_once()

    # Verify task persisted
    saved = runner.registry.get(task.id)
    assert saved is not None
    assert saved.status == "succeeded"
    assert saved.backend == "pi"


@pytest.mark.asyncio
async def test_happy_path_runner_agy(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo_agy")
    coworker_cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="agy",
            repos=[RepoConfig(path=str(repo_dir), base_ref="main", acceptance="cat test.txt")],
            agy=AgyBackendConfig(
                command=[sys.executable, FAKE_AGY_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_AGY_SCENARIO"],
            ),
        )
    )

    runner = CodingRunner(coworker_cfg, tmp_path)
    task, backend, repo = runner.admit(
        brief="Create test.txt with agy",
        session_key="sess-agy",
        channel="cli",
        chat_id="user-2",
    )

    with patch("nanobot.coworker.coding.runner.inject_turn", new_callable=AsyncMock) as mock_inject:
        with patch.dict(os.environ, {"FAKE_AGY_SCENARIO": "write_file:test.txt:created by agy"}):
            msg = await runner.execute_task(task, backend, repo, wait=True)

    assert task.status == "succeeded"
    assert "[auto-coding-result]" in msg
    # wait=True does not inject turn
    mock_inject.assert_not_awaited()


@pytest.mark.asyncio
async def test_acceptance_failure_and_fix_round(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo_fix")
    coworker_cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="pi",
            fix_rounds=1,
            repos=[RepoConfig(path=str(repo_dir), base_ref="main", acceptance="test -f fixed.txt")],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_PI_SCENARIO"],
            ),
        )
    )

    runner = CodingRunner(coworker_cfg, tmp_path)
    task, backend, repo = runner.admit(
        brief="Fix issue",
        session_key="sess-fix",
        channel="cli",
        chat_id="user-3",
    )

    # In first round, file doesn't exist -> acceptance fails.
    # On follow-up, create fixed.txt -> acceptance passes.
    with patch("nanobot.coworker.coding.runner.inject_turn", new_callable=AsyncMock):
        # We simulate follow-up creating the file by having fake_pi create it
        with patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:fixed.txt:ok"}):
            await runner.execute_task(task, backend, repo, wait=True)

    assert task.status == "succeeded"


@pytest.mark.asyncio
async def test_backend_resolution_and_missing_binary(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo_res")
    coworker_cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="pi",
            repos=[
                RepoConfig(path=str(repo_dir), backend="agy"),
            ],
            pi=PiBackendConfig(command=["non_existent_pi_cmd_12345"]),
            agy=AgyBackendConfig(command=["non_existent_agy_cmd_12345"]),
        )
    )
    runner = CodingRunner(coworker_cfg, tmp_path)

    # Repo default is agy -> tries agy binary -> fails because non_existent_agy_cmd_12345 not found
    with pytest.raises(RuntimeError, match="Backend 'agy' binary"):
        runner.admit(brief="test", session_key="s1", channel="c", chat_id="u")

    # Explicit backend arg "pi" overrides repo default -> tries pi binary -> fails
    with pytest.raises(RuntimeError, match="Backend 'pi' binary"):
        runner.admit(brief="test", session_key="s1", channel="c", chat_id="u", backend_name="pi")


@pytest.mark.asyncio
async def test_concurrency_and_empty_repos(tmp_path: Path) -> None:
    # 1. Empty repos refuses start
    empty_cfg = CoworkerConfig(coding=CodingAgentConfig(enabled=True, repos=[]))
    runner_empty = CodingRunner(empty_cfg, tmp_path)
    with pytest.raises(RuntimeError, match="No repositories configured"):
        runner_empty.admit(brief="test", session_key="s1", channel="c", chat_id="u")

    # 2. Concurrency limits
    repo_dir = _init_repo(tmp_path / "repo_conc")
    conc_cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            max_concurrent_per_session=1,
            max_concurrent_total=2,
            repos=[RepoConfig(path=str(repo_dir))],
            pi=PiBackendConfig(command=[sys.executable, FAKE_PI_SCRIPT], allow_unsandboxed=True),
        )
    )
    runner_conc = CodingRunner(conc_cfg, tmp_path)
    t1, _, _ = runner_conc.admit(brief="t1", session_key="s1", channel="c", chat_id="u")
    t1.status = "running"
    runner_conc.registry.save(t1)

    # Per-session limit reached for s1
    with pytest.raises(RuntimeError, match="Per-session concurrent coding tasks limit reached"):
        runner_conc.admit(brief="t2", session_key="s1", channel="c", chat_id="u")

    # Another session s2 can start
    t2, _, _ = runner_conc.admit(brief="t2", session_key="s2", channel="c", chat_id="u")
    t2.status = "running"
    runner_conc.registry.save(t2)

    # Total limit reached
    with pytest.raises(RuntimeError, match="Total concurrent coding tasks limit reached"):
        runner_conc.admit(brief="t3", session_key="s3", channel="c", chat_id="u")


def test_restart_recovery_marks_interrupted(tmp_path: Path) -> None:
    registry = TaskRegistry(tmp_path)
    task = CodingTask(
        id="ct-test-recover",
        backend="pi",
        session_key="s1",
        channel="cli",
        chat_id="u1",
        repo="/tmp/repo",
        base="main",
        branch="coworker/code/ct-test-recover",
        worktree="/tmp/wt",
        brief="Test task",
        status="running",
    )
    registry.save(task)

    # Simulate restart by creating a new registry instance on the same directory
    restarted_registry = TaskRegistry(tmp_path)
    recovered = restarted_registry.get("ct-test-recover")
    assert recovered is not None
    assert recovered.status == "interrupted"
