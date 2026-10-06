"""Regression test for C2: Watchdog detecting idle timeout when no events arrive."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding.backends.base import BackendEventDone, BackendResult, BackendRun
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.config import CodingAgentConfig, CoworkerConfig, RepoConfig


class StalledBackend:
    name = "fake"

    def __init__(self) -> None:
        self.aborted = False
        self.queue: asyncio.Queue = asyncio.Queue()

    def start(self, **kwargs) -> BackendRun:
        backend_self = self

        class _Run(BackendRun):
            async def __aiter__(self):
                while True:
                    ev = await backend_self.queue.get()
                    yield ev
                    if isinstance(ev, BackendEventDone):
                        break

        return _Run()

    async def abort(self) -> None:
        self.aborted = True
        # abort unblocks the run by pushing a terminal event or exiting
        await self.queue.put(
            BackendEventDone(
                result=BackendResult(status="aborted", error="Aborted by watchdog"),
                resume_ref=None,
            )
        )


@pytest.mark.asyncio
async def test_watchdog_idle_timeout(tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("Init", encoding="utf-8")

    coworker_cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="pi",
            timeout_minutes=10,
            idle_timeout_minutes=1,  # We will mock time
            repos=[RepoConfig(path=str(repo_dir), base_ref="main")],
        )
    )

    runner = CodingRunner(coworker_cfg, tmp_path)
    backend = StalledBackend()

    task, _, repo = runner.admit(
        brief="Test watchdog stall",
        session_key="sess-watchdog",
        channel="cli",
        chat_id="user-1",
    )

    # Fast forward time in watchdog
    start_sim_time = 1000.0
    current_sim_time = [start_sim_time]

    def mock_time():
        return current_sim_time[0]

    with patch("time.time", side_effect=mock_time):
            with patch("nanobot.coworker.coding.runner.inject_turn", new_callable=AsyncMock), \
                 patch("nanobot.coworker.coding.orchestrator.inject_turn", new_callable=AsyncMock), \
                 patch.object(runner.orchestrator.workspace_mgr, "create_worktree", new_callable=AsyncMock) as mock_wt, \
                 patch.object(runner.workspace_mgr, "create_worktree", new_callable=AsyncMock):
                mock_wt.return_value = (repo_dir, "coworker/code/test-wt")

                exec_task = asyncio.create_task(runner.execute_task(task, backend, repo, wait=False))

                # Let watchdog start
                await asyncio.sleep(0.1)

                # Advance simulated time beyond idle_timeout_minutes (60 seconds)
                current_sim_time[0] += 120.0

                # Wait for watchdog to trigger and execute_task to complete
                await asyncio.wait_for(exec_task, timeout=5.0)

    assert backend.aborted is True
    assert task.status == "timed_out"
    assert "Idle timeout" in (task.error or "")
