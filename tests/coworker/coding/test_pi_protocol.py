"""Tests for Pi RPC protocol parsing."""

import json
from pathlib import Path

from nanobot.coworker.coding.pi.protocol import (
    AgentStartEvent,
    MessageStartEvent,
    Response,
    ToolExecutionStartEvent,
    parse_rpc_event,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "coworker" / "plans" / "fixtures" / "pi-1.x"


def test_protocol_parses_real_fixtures() -> None:
    stdout_file = FIXTURES_DIR / "01-success-tool.stdout.jsonl"
    lines = stdout_file.read_text(encoding="utf-8").strip().splitlines()

    # Line 0 is initial response to prompt
    resp_raw = json.loads(lines[0])
    resp = Response.from_dict(resp_raw)
    assert resp.success is True
    assert resp.command == "prompt"
    assert resp.data.get("disposition") == "started"

    events = [parse_rpc_event(json.loads(line)) for line in lines[1:]]
    assert isinstance(events[0], AgentStartEvent)
    assert isinstance(events[2], MessageStartEvent)
    assert any(isinstance(e, ToolExecutionStartEvent) for e in events)


def test_protocol_parses_error_response() -> None:
    stdout_file = FIXTURES_DIR / "02-rejected-command.stdout.jsonl"
    lines = stdout_file.read_text(encoding="utf-8").strip().splitlines()
    resp = Response.from_dict(json.loads(lines[0]))
    assert resp.success is False
    assert "Model not found" in (resp.error or "")
