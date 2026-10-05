"""Guest output contract parse, repair, and AgentRuntime retry."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.runner import AgentRunResult
from nanobot.coworker.agents.contract import parse_guest_contract
from nanobot.coworker.agents.home import scaffold_agent_home
from nanobot.coworker.agents.runtime import AgentRuntime
from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.runtime import CoworkerServices


def test_parse_valid_contract() -> None:
    text = 'notes\n```json\n{"summary": "done", "confidence": "high"}\n```'
    payload, errors = parse_guest_contract(text)
    assert errors == []
    assert payload == {"summary": "done", "confidence": "high"}


def test_parse_missing_and_invalid() -> None:
    payload, errors = parse_guest_contract("just prose")
    assert payload is None and errors
    payload, errors = parse_guest_contract('```json\n{"summary": "x"}\n```')
    assert payload is None
    assert any("confidence" in e for e in errors)


def _svc(tmp_path: Path) -> CoworkerServices:
    return CoworkerServices(
        workspace=tmp_path,
        bus=None,  # type: ignore[arg-type]
        sessions=None,  # type: ignore[arg-type]
        subagents=None,
        provider_snapshot_loader=None,
    )


@pytest.mark.asyncio
async def test_runtime_repairs_invalid_contract_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = RoomAgentConfig(id="helper", home="agents/helper")
    scaffold_agent_home(tmp_path, agent)
    runtime = AgentRuntime(_svc(tmp_path), CoworkerConfig(room=RoomConfig(agents=[agent])))
    replies = [
        AgentRunResult(
            final_content="no json here",
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "task"},
                {"role": "assistant", "content": "no json here"},
            ],
            stop_reason="completed",
        ),
        AgentRunResult(
            final_content='```json\n{"summary": "fixed", "confidence": "medium"}\n```',
            messages=[],
            stop_reason="completed",
        ),
    ]
    runtime.runner.run = AsyncMock(side_effect=replies)  # type: ignore[method-assign]
    monkeypatch.setattr("nanobot.coworker.agents.runtime.build_tools", lambda *a, **k: MagicMock())
    guest = await runtime.run(
        agent,
        "task",
        room_id="r1",
        session_key="cli:direct",
        channel="cli",
        chat_id="direct",
        project_root=tmp_path,
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )
    assert runtime.runner.run.await_count == 2
    assert guest.contract == {"summary": "fixed", "confidence": "medium"}
    repair_msgs = runtime.runner.run.await_args_list[1].args[0].initial_messages
    assert repair_msgs[0]["role"] == "system"
    assert "Fix EXACTLY these problems" in repair_msgs[-1]["content"]


@pytest.mark.asyncio
async def test_runtime_accepts_low_confidence_after_two_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = RoomAgentConfig(id="helper", home="agents/helper")
    scaffold_agent_home(tmp_path, agent)
    runtime = AgentRuntime(_svc(tmp_path), CoworkerConfig(room=RoomConfig(agents=[agent])))
    bad = AgentRunResult(final_content="still broken", messages=[], stop_reason="completed")
    runtime.runner.run = AsyncMock(return_value=bad)  # type: ignore[method-assign]
    monkeypatch.setattr("nanobot.coworker.agents.runtime.build_tools", lambda *a, **k: MagicMock())
    guest = await runtime.run(
        agent,
        "task",
        room_id="r1",
        session_key="cli:direct",
        channel="cli",
        chat_id="direct",
        project_root=tmp_path,
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )
    assert runtime.runner.run.await_count == 2
    assert guest.contract is None
    assert guest.contract_failed is True
    assert guest.text == "still broken"


@pytest.mark.asyncio
async def test_runtime_skips_repair_on_error_stop_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = RoomAgentConfig(id="helper", home="agents/helper")
    scaffold_agent_home(tmp_path, agent)
    runtime = AgentRuntime(_svc(tmp_path), CoworkerConfig(room=RoomConfig(agents=[agent])))
    runtime.runner.run = AsyncMock(  # type: ignore[method-assign]
        return_value=AgentRunResult(final_content="provider down", messages=[], stop_reason="error")
    )
    monkeypatch.setattr("nanobot.coworker.agents.runtime.build_tools", lambda *a, **k: MagicMock())
    guest = await runtime.run(
        agent,
        "task",
        room_id="r1",
        session_key="cli:direct",
        channel="cli",
        chat_id="direct",
        project_root=tmp_path,
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )
    assert runtime.runner.run.await_count == 1
    assert guest.contract is None
    assert guest.contract_failed is True


@pytest.mark.asyncio
async def test_output_contract_none_skips_parse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    agent = RoomAgentConfig(id="helper", home="agents/helper", output_contract="none")
    scaffold_agent_home(tmp_path, agent)
    runtime = AgentRuntime(_svc(tmp_path), CoworkerConfig(room=RoomConfig(agents=[agent])))
    runtime.runner.run = AsyncMock(  # type: ignore[method-assign]
        return_value=AgentRunResult(final_content="plain", messages=[], stop_reason="completed")
    )
    monkeypatch.setattr("nanobot.coworker.agents.runtime.build_tools", lambda *a, **k: MagicMock())
    guest = await runtime.run(
        agent,
        "task",
        room_id="r1",
        session_key="cli:direct",
        channel="cli",
        chat_id="direct",
        project_root=tmp_path,
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
    )
    assert runtime.runner.run.await_count == 1
    assert guest.contract is None
    assert guest.text == "plain"
