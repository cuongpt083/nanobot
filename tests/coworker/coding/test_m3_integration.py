"""Milestone M3 tests: tool contract, commands routing, hook visibility, and merge policies."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.agent.tools.context import RequestContext
from nanobot.command.router import CommandContext
from nanobot.coworker.coding.commands import cmd_code
from nanobot.coworker.coding.tools import CodingAgentTool
from nanobot.coworker.config import (
    CodingAgentConfig,
    CoworkerConfig,
    PiBackendConfig,
    RepoConfig,
)
from nanobot.coworker.hook import CoworkerHook
from nanobot.coworker.runtime import CoworkerServices, set_services

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    (path / "file.txt").write_text("initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=path, check=True)
    return path


def _mock_cmd_context(args: str) -> CommandContext:
    msg = MagicMock()
    msg.channel = "cli"
    msg.chat_id = "user1"
    msg.metadata = {}
    ctx = MagicMock(spec=CommandContext)
    ctx.args = args
    ctx.msg = msg
    ctx.key = "cli:user1"
    return ctx


@pytest.mark.asyncio
async def test_tool_visibility_via_hook() -> None:
    turn = AgentTurnHookContext(channel="cli", chat_id="direct", session_key="cli:u1")
    hook = CoworkerHook(turn)
    agent_ctx = MagicMock(spec=AgentHookContext)

    tools = [
        {"type": "function", "function": {"name": "coding_agent"}},
        {"type": "function", "function": {"name": "read_file"}},
    ]
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "hi"},
    ]

    # 1. coding.enabled = False -> coding_agent hidden
    cfg_disabled = CoworkerConfig(coding=CodingAgentConfig(enabled=False))
    with patch("nanobot.coworker.hook.load_coworker_config", return_value=cfg_disabled):
        with patch("nanobot.coworker.hook.get_session", return_value=MagicMock()):
            with patch("nanobot.coworker.hook.services", return_value=MagicMock()):
                _, filtered_tools = hook.transform_request(agent_ctx, messages, tools, stateful=False)
                assert filtered_tools is not None
                names = [t["function"]["name"] for t in filtered_tools]
                assert "coding_agent" not in names
                assert "read_file" in names

    # 2. coding.enabled = True -> coding_agent visible, directive appended
    cfg_enabled = CoworkerConfig(coding=CodingAgentConfig(enabled=True))
    with patch("nanobot.coworker.hook.load_coworker_config", return_value=cfg_enabled):
        with patch("nanobot.coworker.hook.get_session", return_value=MagicMock()):
            with patch("nanobot.coworker.hook.services", return_value=MagicMock()):
                transformed_msgs, filtered_tools = hook.transform_request(agent_ctx, messages, tools, stateful=False)
                assert filtered_tools is not None
                names = [t["function"]["name"] for t in filtered_tools]
                assert "coding_agent" in names
                # Check directive
                assert any("External coding agent delegation" in m.get("content", "") for m in transformed_msgs)


@pytest.mark.asyncio
async def test_tool_execute_actions(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo_tool")
    cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            repos=[RepoConfig(path=str(repo_dir), base_ref="main")],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_PI_SCENARIO"],
            ),
        )
    )

    mock_svc = MagicMock(spec=CoworkerServices)
    mock_svc.workspace = tmp_path
    set_services(mock_svc)

    tool = CodingAgentTool()

    req_ctx = RequestContext(session_key="s1", channel="cli", chat_id="u1")
    with patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg):
        with patch.object(CodingAgentTool, "request", return_value=req_ctx):
            # 1. Action: start with wait=True
            with patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:file.txt:modified"}):
                res = await tool.execute(action="start", task="Refactor file.txt", wait=True)
                assert not res.is_error
                assert "[auto-coding-result]" in str(res)

            # 2. Action: start with background spawn
            def _close_coro(coro: Any, **kw: Any) -> None:
                coro.close()

            with patch("nanobot.coworker.coding.tools.spawn_background", side_effect=_close_coro):
                res_bg = await tool.execute(action="start", task="Refactor in background", wait=False)
                assert not res_bg.is_error
                assert "started" in str(res_bg)

            data = json.loads(str(res_bg))
            task_id = data["id"]

            # 3. Action: status
            res_status = await tool.execute(action="status", id=task_id)
            assert not res_status.is_error
            assert task_id in str(res_status)

            # 4. Action: abort
            res_abort = await tool.execute(action="abort", id=task_id)
            assert not res_abort.is_error

            # 5. Action: result
            res_result = await tool.execute(action="result", id=task_id)
            assert not res_result.is_error


@pytest.mark.asyncio
async def test_commands_merge_and_discard(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo_cmds")
    cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            repos=[RepoConfig(path=str(repo_dir), base_ref="main")],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_PI_SCENARIO"],
            ),
        )
    )

    mock_svc = MagicMock(spec=CoworkerServices)
    mock_svc.workspace = tmp_path
    set_services(mock_svc)

    with patch("nanobot.coworker.coding.commands.load_coworker_config", return_value=cfg):
        # 1. /code list (empty)
        ctx = _mock_cmd_context("list")
        resp = await cmd_code(ctx)
        assert "No coding tasks found" in resp.content

        # 2. Run a task to merge
        tool = CodingAgentTool()
        req_ctx = RequestContext(session_key="s1", channel="cli", chat_id="u1")
        with patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg):
            with patch.object(CodingAgentTool, "request", return_value=req_ctx):
                with patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:file.txt:merged content"}):
                    await tool.execute(action="start", task="Task to merge", wait=True)

        # Get task ID from list
        ctx_list = _mock_cmd_context("list")
        resp_list = await cmd_code(ctx_list)
        assert "Task to merge" in resp_list.content

        m = re.search(r"(ct-\d+-\d+-[a-z0-9]+)", resp_list.content)
        assert m is not None
        task_id = m.group(1)

        # 3. /code status
        ctx_stat = _mock_cmd_context(f"status {task_id}")
        resp_stat = await cmd_code(ctx_stat)
        assert task_id in resp_stat.content

        # 4. /code diff
        ctx_diff = _mock_cmd_context(f"diff {task_id}")
        resp_diff = await cmd_code(ctx_diff)
        assert "merged content" in resp_diff.content

        # 5. /code merge refused if main checkout is dirty
        (repo_dir / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        subprocess.run(["git", "add", "dirty.txt"], cwd=repo_dir, check=True)
        ctx_merge_dirty = _mock_cmd_context(f"merge {task_id}")
        resp_dirty = await cmd_code(ctx_merge_dirty)
        assert "uncommitted or unstaged changes" in resp_dirty.content

        # Clean up dirty change
        subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=repo_dir, check=True)
        subprocess.run(["git", "clean", "-fd"], cwd=repo_dir, check=True)

        # 6. /code merge succeeded
        ctx_merge_ok = _mock_cmd_context(f"merge {task_id}")
        resp_merge_ok = await cmd_code(ctx_merge_ok)
        assert "Successfully merged" in resp_merge_ok.content

        # Verify change is on main
        content = (repo_dir / "file.txt").read_text(encoding="utf-8")
        assert "merged content" in content

        # 7. /code discard on another task
        with patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg):
            with patch.object(CodingAgentTool, "request", return_value=req_ctx):
                def _close_disc(coro: Any, **kw: Any) -> None:
                    coro.close()

                with patch("nanobot.coworker.coding.tools.spawn_background", side_effect=_close_disc):
                    res_disc = await tool.execute(action="start", task="Task to discard", wait=False)
                    t_id_disc = json.loads(str(res_disc))["id"]

        ctx_disc = _mock_cmd_context(f"discard {t_id_disc}")
        resp_disc = await cmd_code(ctx_disc)
        assert "Discarded task" in resp_disc.content
