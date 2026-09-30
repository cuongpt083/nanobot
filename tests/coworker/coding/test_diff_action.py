"""coding_agent(action="diff"): the executor (and therefore the advisor) can read the real changes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.agent.tools.context import RequestContext
from nanobot.coworker.coding import tools as coding_tools
from nanobot.coworker.coding.tasks import shared_registry
from nanobot.coworker.coding.tools import CodingAgentTool
from nanobot.coworker.config import CodingAgentConfig, CoworkerConfig, PiBackendConfig, RepoConfig
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


@pytest.fixture
def coding_env(tmp_path: Path):
    repo_dir = _init_repo(tmp_path / "repo_diff")
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
    svc = MagicMock(spec=CoworkerServices)
    svc.workspace = tmp_path
    set_services(svc)
    yield tmp_path, cfg
    set_services(None)


async def _run_task(cfg: CoworkerConfig) -> CodingAgentTool:
    tool = CodingAgentTool()
    req = RequestContext(session_key="s1", channel="cli", chat_id="u1")
    with (
        patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg),
        patch.object(CodingAgentTool, "request", return_value=req),
        patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:file.txt:modified"}),
    ):
        res = await tool.execute(action="start", task="Modify file.txt", wait=True)
    assert not res.is_error
    return tool


@pytest.mark.asyncio
async def test_diff_returns_the_worktree_changes(coding_env) -> None:
    tmp_path, cfg = coding_env
    tool = await _run_task(cfg)
    task = shared_registry(tmp_path).list_tasks()[0]
    with patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg):
        out = json.loads(await tool.execute(action="diff", id=task.id))
    assert out["status"] == "ok" and out["id"] == task.id
    assert "+modified" in out["diff"] and out["truncated"] is False


@pytest.mark.asyncio
async def test_diff_is_capped_and_says_so(coding_env, monkeypatch) -> None:
    tmp_path, cfg = coding_env
    tool = await _run_task(cfg)
    task = shared_registry(tmp_path).list_tasks()[0]
    monkeypatch.setattr(coding_tools, "DIFF_MAX_CHARS", 40)
    with patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg):
        out = json.loads(await tool.execute(action="diff", id=task.id))
    assert out["truncated"] is True and len(out["diff"]) == 40
    assert out["total_chars"] > 40 and "truncated" in out["note"]


@pytest.mark.asyncio
async def test_diff_errors_are_explicit(coding_env) -> None:
    tmp_path, cfg = coding_env
    tool = CodingAgentTool()
    with patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg):
        assert "'id' is required" in str(await tool.execute(action="diff"))
        assert "not found" in str(await tool.execute(action="diff", id="ct-nope"))
