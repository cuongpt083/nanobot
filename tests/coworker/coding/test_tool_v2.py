"""Unit tests for tool v2 actions and schema validations."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nanobot.coworker.coding.tools import CodingAgentTool
from nanobot.coworker.config import CoworkerConfig


def _parse_payload(res) -> dict:
    return json.loads(str(res))


@pytest.mark.asyncio
async def test_tool_start_missing_parameters_rejected():
    tool = CodingAgentTool()
    res = await tool.execute(action="start")
    data = _parse_payload(res)
    assert data.get("status") == "error"
    assert "Required parameters for action='start'" in data.get("error", "")


@pytest.mark.asyncio
async def test_tool_start_contract_validation_failure():
    cfg = CoworkerConfig()
    cfg.coding.enabled = True
    with patch("nanobot.coworker.coding.tools.load_coworker_config", return_value=cfg):
        tool = CodingAgentTool()
        res = await tool.execute(
            action="start",
            objective="Short task",
            context="Short",
            acceptance_criteria=[],
        )
        data = _parse_payload(res)
        assert data.get("status") == "error"
        assert "Contract validation failed" in data.get("error", "")


@pytest.mark.asyncio
async def test_tool_plan_actions_validation():
    tool = CodingAgentTool()

    # Missing id
    res_approve = await tool.execute(action="approve")
    data_approve = _parse_payload(res_approve)
    assert data_approve.get("status") == "error"

    res_revise = await tool.execute(action="revise_plan")
    data_revise = _parse_payload(res_revise)
    assert data_revise.get("status") == "error"

    # Non-existent task id
    res_approve_none = await tool.execute(action="approve", id="ct-nonexistent")
    data_none = _parse_payload(res_approve_none)
    assert data_none.get("status") == "error"
    assert "not found" in data_none.get("error", "")


@pytest.mark.asyncio
async def test_tool_answer_action():
    tool = CodingAgentTool()

    # Missing question_id
    res_no_qid = await tool.execute(action="answer", id="ct-123")
    data_no_qid = _parse_payload(res_no_qid)
    assert data_no_qid.get("status") == "error"
    assert "question_id" in data_no_qid.get("error", "")

    # Nonexistent task id
    res_no_task = await tool.execute(action="answer", id="ct-123", question_id="q-1", answer="yes")
    data_no_task = _parse_payload(res_no_task)
    assert data_no_task.get("status") == "error"
    assert "not found" in data_no_task.get("error", "")
