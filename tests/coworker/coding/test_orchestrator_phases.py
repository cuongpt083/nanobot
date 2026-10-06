"""Comprehensive tests for Phase 4 orchestrator phases, reviewer isolation, delivery, wait mode, and direct mode."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding.contract import CodingContract
from nanobot.coworker.coding.orchestrator import format_delivery_message
from nanobot.coworker.coding.review import render_reviewer_prompt
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.tasks import CodingTask
from nanobot.coworker.config import (
    CodingAgentConfig,
    CoworkerConfig,
    PiBackendConfig,
    RepoConfig,
)

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    (path / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, check=True)
    return path


@pytest.mark.asyncio
async def test_review_isolation_prompt_content(tmp_path: Path) -> None:
    task = CodingTask(
        id="ct-review-1",
        backend="pi",
        session_key="s1",
        channel="cli",
        chat_id="u1",
        repo=str(tmp_path),
        base="main",
        branch="coworker/code/ct-review-1",
        worktree=str(tmp_path),
        brief="Fix issue #123",
        contract={
            "objective": "Resolve edge case in auth token validation",
            "acceptance_criteria": ["All tests in test_auth.py pass"],
        },
        plan={"summary": "1. Check auth.py 2. Run pytest", "plan_steps": ["Check auth", "Run pytest"]},
    )

    prompt = render_reviewer_prompt(task)
    assert "Resolve edge case in auth token validation" in prompt
    assert "All tests in test_auth.py pass" in prompt
    assert "Check auth" in prompt
    assert "report_result(kind='review'" in prompt
    # Builder transcript is never included
    assert "builder:" not in prompt.lower()
    assert "assistant text" not in prompt.lower()


@pytest.mark.asyncio
async def test_delivery_message_formatting() -> None:
    task = CodingTask(
        id="ct-deliv-1",
        backend="pi",
        session_key="s1",
        channel="cli",
        chat_id="u1",
        repo="/tmp/repo",
        base="main",
        branch="b1",
        worktree="/tmp/repo",
        brief="Sample brief",
        status="succeeded",
        phase="deliver",
        contract={"objective": "Structured objective"},
        summary="Work done",
        diffstat="1 file changed, 1 insertion(+)",
        commits=["feat: initial"],
        review={"verdict": "pass", "findings": []},
        blocked_calls=2,
    )
    msg = format_delivery_message(task)
    assert "[auto-coding-result]" in msg
    assert "finished with status: `succeeded`" in msg
    assert "**Phase**: deliver" in msg
    assert "**Goal**: Sample brief" in msg
    assert "1 file changed" in msg
    assert "/code merge" in msg


@pytest.mark.asyncio
async def test_wait_mode_rejection_when_exceeding_timeout(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo")
    cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            timeout_minutes=5,
            wait_max_minutes=10,  # Exceeds timeout
            repos=[RepoConfig(path=str(repo_dir), base_ref="main")],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
            ),
        )
    )
    runner = CodingRunner(cfg, tmp_path)
    task, backend, repo = runner.admit(
        brief="Quick task",
        session_key="s1",
        channel="cli",
        chat_id="u1",
    )
    msg = await runner.execute_task(task, backend, repo, wait=True)
    assert task.status == "error"
    assert "wait_max_minutes (10) exceeds timeout_minutes (5)" in (task.error or "")
    assert "finished with status: `error`" in msg


@pytest.mark.asyncio
async def test_orchestrator_phases_full_flow(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo_phase")
    cfg = CoworkerConfig(
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
    runner = CodingRunner(cfg, tmp_path)
    task, backend, repo = runner.admit(
        brief="Test orchestrator phases",
        session_key="s1",
        channel="cli",
        chat_id="u1",
    )
    task.contract = CodingContract(
        objective="Create test.txt",
        context="A full phase test verification " * 5,
        acceptance_criteria=["test.txt exists"],
        mode="plan_first",
    ).to_dict()

    with patch("nanobot.coworker.coding.orchestrator.inject_turn", new_callable=AsyncMock) as mock_inject, \
         patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:test.txt:phase content"}):
        await runner.execute_task(task, backend, repo, wait=False)

    assert task.status == "succeeded"
    assert task.phase == "deliver"
    assert task.pi_session_file is not None
    mock_inject.assert_awaited()
    # Contract json created in run_dir
    contract_file = task.run_dir / "task-contract.json"
    assert contract_file.exists()
