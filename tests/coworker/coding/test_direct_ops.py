"""Tool actions and /code commands for tasks that edited a non-git project in place."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.tools.context import RequestContext
from nanobot.command.router import CommandContext
from nanobot.coworker.coding.commands import cmd_code
from nanobot.coworker.coding.tasks import CodingTask, reset_shared_registries
from nanobot.coworker.coding.tools import CodingAgentTool
from nanobot.coworker.config import CodingAgentConfig, CoworkerConfig, PiBackendConfig
from nanobot.coworker.runtime import CoworkerServices, set_services

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")


class Env(SimpleNamespace):
    project: Path
    tool: CodingAgentTool


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    project = tmp_path / "docs"
    project.mkdir()
    (project / "notes.md").write_text("original\n", encoding="utf-8")
    (project / "deck.txt").write_text("slide\n", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="pi",
            repos=[],
            non_git="direct",
            max_concurrent_per_session=3,
            max_concurrent_total=3,
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_PI_SCENARIO"],
            ),
        )
    )
    session = SimpleNamespace(
        metadata={"workspace_scope": {"project_path": str(project), "access_mode": "restricted"}}
    )
    svc = MagicMock(spec=CoworkerServices)
    svc.workspace = workspace
    set_services(svc)
    reset_shared_registries()
    patches = [
        patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg),
        patch("nanobot.coworker.coding.commands.load_coworker_config", return_value=cfg),
        patch("nanobot.coworker.coding.runner._lookup_session", return_value=session),
        patch.object(
            CodingAgentTool,
            "request",
            return_value=RequestContext(session_key="s1", channel="cli", chat_id="u1"),
        ),
    ]
    for p in patches:
        p.start()
    try:
        yield Env(project=project, tool=CodingAgentTool())
    finally:
        for p in patches:
            p.stop()
        set_services(None)
        reset_shared_registries()


def _ctx(args: str) -> CommandContext:
    ctx = MagicMock(spec=CommandContext)
    ctx.args = args
    ctx.msg = SimpleNamespace(channel="cli", chat_id="u1", metadata={})
    ctx.key = "cli:u1"
    ctx.session = None
    return ctx


async def _run_task(env: Env, scenario: str) -> dict[str, Any]:
    with patch.dict(os.environ, {"FAKE_PI_SCENARIO": scenario}):
        res = await env.tool.execute(action="start", task="edit the notes", wait=True)
    assert not res.is_error, str(res)
    runner = env.tool._get_runner()  # noqa: SLF001
    task = runner.registry.list_tasks()[0]
    return {"id": task.id, "task": task, "runner": runner}


@pytest.mark.asyncio
async def test_tool_diff_and_status_for_an_in_place_task(env: Env) -> None:
    run = await _run_task(env, "write_file:notes.md:rewritten by pi")
    task: CodingTask = run["task"]
    assert task.mode == "direct" and task.changes["modified"] == ["notes.md"]

    diff = json.loads(str(await env.tool.execute(action="diff", id=run["id"])))
    assert diff["status"] == "ok" and diff["mode"] == "direct"
    assert diff["changes"]["modified"] == ["notes.md"]
    assert "+rewritten by pi" in diff["diff"] and "-original" in diff["diff"]

    status = json.loads(str(await env.tool.execute(action="status", id=run["id"])))
    assert status["mode"] == "direct" and status["changes"]["modified"] == ["notes.md"]


@pytest.mark.asyncio
async def test_tool_diff_without_changes_or_snapshot(env: Env) -> None:
    run = await _run_task(env, "write_file:notes.md:rewritten by pi")
    task: CodingTask = run["task"]

    task.changes = {}
    empty = json.loads(str(await env.tool.execute(action="diff", id=run["id"])))
    assert empty["note"] == "No files were changed."

    task.changes = {"modified": ["notes.md"]}
    task.snapshot = str(env.project / "missing-snapshot")
    err = await env.tool.execute(action="diff", id=run["id"])
    assert err.is_error and "snapshot" in str(err)


@pytest.mark.asyncio
async def test_commands_list_status_diff_and_merge(env: Env) -> None:
    run = await _run_task(env, "write_file:notes.md:rewritten by pi")
    task_id = run["id"]

    assert "in place" in (await cmd_code(_ctx("list"))).content
    status = (await cmd_code(_ctx(f"status {task_id}"))).content
    assert "edited in place" in status and "~ notes.md" in status and "Commits" not in status
    diff = (await cmd_code(_ctx(f"diff {task_id}"))).content
    assert "+rewritten by pi" in diff
    merge = (await cmd_code(_ctx(f"merge {task_id}"))).content
    assert "nothing to merge" in merge and f"/code discard {task_id}" in merge


@pytest.mark.asyncio
async def test_discard_restores_files_and_keeps_the_project(env: Env) -> None:
    run = await _run_task(env, "write_file:notes.md:rewritten by pi")
    task: CodingTask = run["task"]
    # The user touched nothing after the task, so the restore may go ahead.
    reply = (await cmd_code(_ctx(f"discard {task.id}"))).content
    assert "Undid task" in reply and "1 file(s) restored" in reply
    assert (env.project / "notes.md").read_text(encoding="utf-8") == "original\n"
    assert (env.project / "deck.txt").exists()
    assert task.status == "aborted" and task.changes == {} and task.diffstat == "undone"


@pytest.mark.asyncio
async def test_discard_removes_files_the_task_added(env: Env) -> None:
    run = await _run_task(env, "write_file:made.txt:by pi")
    task: CodingTask = run["task"]
    assert task.changes["added"] == ["made.txt"]
    reply = (await cmd_code(_ctx(f"discard {task.id}"))).content
    assert "1 added file(s) removed" in reply
    assert not (env.project / "made.txt").exists()
    assert env.project.exists()


@pytest.mark.asyncio
async def test_discard_leaves_files_the_user_edited_afterwards_unless_forced(env: Env) -> None:
    run = await _run_task(env, "write_file:notes.md:rewritten by pi")
    task: CodingTask = run["task"]
    task.finished_at = time.time() - 120  # the task ended two minutes ago
    (env.project / "notes.md").write_text("my own edit\n", encoding="utf-8")

    reply = (await cmd_code(_ctx(f"discard {task.id}"))).content
    assert "Not changed" in reply and "notes.md" in reply and "force" in reply
    assert (env.project / "notes.md").read_text(encoding="utf-8") == "my own edit\n"
    assert task.status == "succeeded"  # not undone, so still reportable

    forced = (await cmd_code(_ctx(f"discard {task.id} force"))).content
    assert "1 file(s) restored" in forced
    assert (env.project / "notes.md").read_text(encoding="utf-8") == "original\n"


@pytest.mark.asyncio
async def test_discard_refuses_a_running_task_and_a_lost_snapshot(env: Env) -> None:
    run = await _run_task(env, "write_file:notes.md:rewritten by pi")
    task: CodingTask = run["task"]

    task.status = "running"
    assert "still running" in (await cmd_code(_ctx(f"discard {task.id}"))).content
    task.status = "succeeded"

    task.snapshot = str(env.project / "gone")
    assert "snapshot" in (await cmd_code(_ctx(f"discard {task.id}"))).content
    assert (env.project / "notes.md").read_text(encoding="utf-8") == "rewritten by pi"


@pytest.mark.asyncio
async def test_refresh_after_a_resumed_round_recomputes_the_changes(env: Env) -> None:
    run = await _run_task(env, "write_file:notes.md:rewritten by pi")
    task: CodingTask = run["task"]
    runner = run["runner"]
    (env.project / "extra.txt").write_text("more", encoding="utf-8")  # a later round adds a file

    changes = await runner.refresh_direct_changes(task)
    assert changes.added == ["extra.txt"] and changes.modified == ["notes.md"]
    assert task.diffstat == "1 added, 1 modified, 0 deleted"


@pytest.mark.asyncio
async def test_discard_of_a_worktree_task_is_unchanged(env: Env) -> None:
    runner = env.tool._get_runner()  # noqa: SLF001
    task = CodingTask(
        id="ct-git", backend="pi", session_key="s1", channel="cli", chat_id="u1",
        repo=str(env.project), base="main", branch="coworker/code/ct-git", worktree="", brief="x",
    )
    with pytest.raises(RuntimeError, match="did not edit in place"):
        await runner.discard_direct(task)
