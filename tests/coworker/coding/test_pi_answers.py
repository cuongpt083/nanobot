"""The ``answer`` action routes to the task's QuestionRouter (ask_coordinator)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.coworker.coding.pi.questions import QuestionRouter, register_router, unregister_router
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.tasks import CodingTask
from nanobot.coworker.coding.tools import CodingAgentTool
from nanobot.coworker.config import CodingAgentConfig, CoworkerConfig


def _runner_with_task(tmp_path: Path) -> CodingRunner:
    cfg = CoworkerConfig(coding=CodingAgentConfig(enabled=True, repos=[]))
    runner = CodingRunner(cfg, tmp_path)
    runner.registry.save(
        CodingTask(
            id="ct-q1",
            backend="pi",
            session_key="s",
            channel="cli",
            chat_id="u",
            repo=str(tmp_path),
            base="main",
            branch="b",
            worktree="",
            brief="x",
            status="running",
        )
    )
    return runner


@pytest.mark.asyncio
async def test_answer_resolves_a_pending_question(tmp_path: Path) -> None:
    runner = _runner_with_task(tmp_path)
    router = QuestionRouter(default_timeout_s=5)
    register_router("ct-q1", router)
    try:
        pending = asyncio.create_task(
            router.handle_extension_ui_request(
                request_id="q-1",
                task_id="ct-q1",
                method="input",
                title="nanobot:ask:design",
                message="Which design?",
            )
        )
        await asyncio.sleep(0.01)
        assert router.get_pending("q-1") is not None

        tool = CodingAgentTool()
        with patch.object(CodingAgentTool, "_get_runner", return_value=runner):
            res = await tool.execute(action="answer", id="ct-q1", question_id="q-1", answer="Option B")

        data = json.loads(str(res))
        assert data["status"] == "ok" and data["state"] == "answered"
        reply = await asyncio.wait_for(pending, timeout=2)
        assert reply["value"] == "Option B"
    finally:
        unregister_router("ct-q1")


@pytest.mark.asyncio
async def test_answer_rejects_unknown_question(tmp_path: Path) -> None:
    runner = _runner_with_task(tmp_path)
    register_router("ct-q1", QuestionRouter(default_timeout_s=5))
    try:
        tool = CodingAgentTool()
        with patch.object(CodingAgentTool, "_get_runner", return_value=runner):
            res = await tool.execute(action="answer", id="ct-q1", question_id="nope", answer="x")
        assert json.loads(str(res))["status"] == "error"
    finally:
        unregister_router("ct-q1")
