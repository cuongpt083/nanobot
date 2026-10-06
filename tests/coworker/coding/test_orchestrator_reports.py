"""Orchestrator v2: plan/report extraction, per-phase stats, and the review->fix loop."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding.runner import CodingRunner
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


def _runner(tmp_path: Path, **coding: object) -> CodingRunner:
    repo_dir = _init_repo(tmp_path / "repo")
    cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            repos=[RepoConfig(path=str(repo_dir), base_ref="main", acceptance="cat test.txt")],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_PI_SCENARIO", "FAKE_PI_REVIEW_VERDICT", "FAKE_PI_REVIEW_FINDINGS"],
            ),
            **coding,  # type: ignore[arg-type]
        )
    )
    return CodingRunner(cfg, tmp_path)


@pytest.mark.asyncio
async def test_plan_report_and_stats_are_captured(tmp_path: Path) -> None:
    runner = _runner(tmp_path)
    task, client, repo = runner.admit(brief="Do work", session_key="s1", channel="cli", chat_id="u1")

    with patch("nanobot.coworker.coding.orchestrator.inject_turn", new_callable=AsyncMock), \
         patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:test.txt:ok"}):
        await runner.execute_task(task, client, repo, wait=False)

    assert task.status == "succeeded"
    assert task.phase == "deliver"
    # Plan and implementation reports were read back from Pi entries.
    assert task.plan and task.plan["kind"] == "plan"
    assert task.report and task.report["kind"] == "implementation"
    # Reviewer verdict flows through.
    assert task.review and task.review["verdict"] == "pass"
    # Session file and entry cursor captured for resume.
    assert task.pi_session_file
    assert task.entry_cursor
    # Per-phase stats recorded and aggregated.
    assert set(task.phase_stats) >= {"plan", "implement", "review"}
    assert task.stats and task.stats["total_tokens"] > 0


@pytest.mark.asyncio
async def test_changes_requested_runs_a_fix_round_then_fails(tmp_path: Path) -> None:
    runner = _runner(tmp_path, fix_rounds=1)
    task, client, repo = runner.admit(brief="Do work", session_key="s1", channel="cli", chat_id="u1")

    findings = json.dumps([
        {"severity": "blocking", "file": "a.py", "line": 3, "issue": "bug", "fix": "fix it"}
    ])
    with patch("nanobot.coworker.coding.orchestrator.inject_turn", new_callable=AsyncMock), \
         patch.dict(os.environ, {
             "FAKE_PI_SCENARIO": "write_file:test.txt:ok",
             "FAKE_PI_REVIEW_VERDICT": "changes_requested",
             "FAKE_PI_REVIEW_FINDINGS": findings,
         }):
        await runner.execute_task(task, client, repo, wait=False)

    assert task.fix_round == 1
    assert "fix" in task.phase_stats
    assert task.review and task.review["verdict"] == "changes_requested"
    assert task.status == "failed_acceptance"
