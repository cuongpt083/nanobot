"""Resume an interrupted coding task after a simulated gateway restart."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.tasks import CodingTask, reset_shared_registries
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
    (path / "README.md").write_text("# Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=path, check=True)
    return path


def _cfg(repo: Path, **coding: object) -> CoworkerConfig:
    return CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            repos=[RepoConfig(path=str(repo), base_ref="main")],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_PI_SCENARIO"],
            ),
            **coding,  # type: ignore[arg-type]
        )
    )


def _interrupted_task(repo: Path, *, phase: str = "implement") -> CodingTask:
    return CodingTask(
        id="ct-resume-1",
        backend="pi",
        session_key="s1",
        channel="cli",
        chat_id="u1",
        repo=str(repo),
        base="main",
        branch="coworker/code/ct-resume-1",
        worktree=str(repo),
        brief="Do work",
        status="running",
        phase=phase,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_resume_interrupted_implement_completes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    cfg = _cfg(repo)

    runner = CodingRunner(cfg, tmp_path)
    runner.registry.save(_interrupted_task(repo))

    # Simulate a gateway restart: a fresh registry recovers in-flight tasks.
    reset_shared_registries()
    restarted = CodingRunner(cfg, tmp_path)
    task = restarted.registry.get("ct-resume-1")
    assert task is not None and task.status == "interrupted"

    with patch("nanobot.coworker.coding.orchestrator.inject_turn", new_callable=AsyncMock), \
         patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:resumed.txt:ok"}):
        await restarted.resume(task)

    assert task.status == "succeeded"
    assert task.phase == "deliver"


@pytest.mark.asyncio
async def test_resume_await_approval_does_not_spawn_pi(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo2")
    cfg = _cfg(repo)

    runner = CodingRunner(cfg, tmp_path)
    runner.registry.save(_interrupted_task(repo, phase="await_approval"))

    reset_shared_registries()
    restarted = CodingRunner(cfg, tmp_path)
    task = restarted.registry.get("ct-resume-1")
    assert task is not None

    with patch("nanobot.coworker.coding.pi.client.PiClient.start", new_callable=AsyncMock) as mock_start:
        message = await restarted.resume(task)

    mock_start.assert_not_awaited()
    assert task.status == "awaiting_approval"
    assert "awaiting plan approval" in message
