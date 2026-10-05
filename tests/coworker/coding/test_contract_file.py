"""Tests for contract file generation and nanobot-bridge policy verification."""

import json
from pathlib import Path


def test_contract_file_structure(tmp_path: Path) -> None:
    contract_data = {
        "task_id": "ct-123",
        "mode": "implement",
        "root": str(tmp_path),
        "write_roots": [str(tmp_path)],
        "deny_commands": ["^git\\s+push"],
        "deny_read": ["~/.ssh/**"],
        "contract": {
            "objective": "Build feature",
            "context": "Context information",
            "acceptance_criteria": ["Test pass"],
        },
        "settle": {"max_continuations": 2},
        "ask": {"enabled": True},
    }

    contract_file = tmp_path / "task-contract.json"
    contract_file.write_text(json.dumps(contract_data, indent=2), encoding="utf-8")

    assert contract_file.exists()
    loaded = json.loads(contract_file.read_text(encoding="utf-8"))
    assert loaded["task_id"] == "ct-123"
    assert loaded["mode"] == "implement"
    assert "^git\\s+push" in loaded["deny_commands"]
