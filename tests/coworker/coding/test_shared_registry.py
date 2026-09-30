"""Regression: building a runner/registry per tool call must not clobber running tasks."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.coworker.coding import runner as runner_mod
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.tasks import CodingTask, TaskRegistry, shared_registry
from nanobot.coworker.config import CoworkerConfig


def _task(task_id: str = "ct-1") -> CodingTask:
    return CodingTask(id=task_id, backend="pi", session_key="s", channel="cli", chat_id="u", repo="/r",
                      base="main", branch="b", worktree="/w", brief="x", status="running")


def test_shared_registry_is_created_once_per_workspace(tmp_path: Path) -> None:
    first = shared_registry(tmp_path)
    first.save(_task())
    again = shared_registry(tmp_path)
    assert again is first
    assert again.get("ct-1").status == "running"  # recovery did not rerun


def test_direct_construction_still_recovers_interrupted_tasks(tmp_path: Path) -> None:
    TaskRegistry(tmp_path).save(_task())
    assert TaskRegistry(tmp_path).get("ct-1").status == "interrupted"


@pytest.mark.asyncio
async def test_a_second_runner_sees_and_can_abort_the_running_task(tmp_path: Path) -> None:
    aborted: list[str] = []

    class FakeBackend:
        name = "pi"
        capabilities = SimpleNamespace(steer=True)

        async def abort(self) -> None:
            aborted.append("abort")

        async def steer(self, message: str) -> None:
            aborted.append(f"steer:{message}")

    cfg = CoworkerConfig()
    started: Any = CodingRunner(cfg, tmp_path)
    started.registry.save(_task())
    runner_mod._ACTIVE_BACKENDS["ct-1"] = FakeBackend()  # what execute_task does while a harness runs
    try:
        later = CodingRunner(cfg, tmp_path)  # e.g. created for a later coding_agent call
        assert later.registry.get("ct-1").status == "running"
        await later.steer("ct-1", "use a flag")
        await later.abort("ct-1")
    finally:
        runner_mod._ACTIVE_BACKENDS.pop("ct-1", None)
    assert aborted == ["steer:use a flag", "abort"]
    assert later.registry.get("ct-1").status == "aborted"
    await asyncio.sleep(0)
