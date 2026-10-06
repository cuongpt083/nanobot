"""Unit tests for CodingContract and validation rules."""

import json
from pathlib import Path

import pytest

from nanobot.coworker.coding.contract import CodingContract


def test_contract_validation_success():
    contract = CodingContract(
        objective="Implement feature X",
        context="This is a comprehensive context description providing detailed architecture requirements and background for this task (more than 120 chars).",
        acceptance_criteria=["Feature X passes pytest", "Type checking passes"],
        constraints=["Do not modify core modules"],
        out_of_scope=["Phase 4 features"],
        acceptance_cmd="pytest tests/feature_x",
        files=["feature_x.py"],
    )

    errors = contract.validate(min_context_chars=120)
    assert errors == []


def test_contract_validation_missing_fields():
    contract = CodingContract(
        objective="",
        context="short context",
        acceptance_criteria=[],
    )

    errors = contract.validate(min_context_chars=120)
    assert len(errors) == 3
    assert any("missing required 'objective'" in e for e in errors)
    assert any("too brief" in e for e in errors)
    assert any("missing 'acceptance_criteria'" in e for e in errors)


def test_contract_write_task_contract_json(tmp_path: Path):
    contract = CodingContract(
        objective="Fix memory leak",
        context="A lengthy context detailing how the memory leak occurs in event listener subscriptions and requires cleanup on disconnect.",
        acceptance_criteria=["Leak test passes"],
        acceptance_cmd="pytest -k test_leak",
    )

    target_file = tmp_path / "subdir" / "task-contract.json"
    written = contract.write_task_contract_json(
        target_file,
        task_id="ct-leak-01",
        worktree_root=tmp_path,
        bridge_mode="implement",
        ask_enabled=True,
    )

    assert written.exists()
    data = json.loads(written.read_text(encoding="utf-8"))
    assert data["task_id"] == "ct-leak-01"
    assert data["mode"] == "implement"
    assert data["root"] == str(tmp_path)
    assert data["contract"]["objective"] == "Fix memory leak"
    assert data["contract"]["acceptance_cmd"] == "pytest -k test_leak"
    assert data["ask"]["enabled"] is True
