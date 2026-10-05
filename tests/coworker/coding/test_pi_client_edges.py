"""Tests for PiClient using mocked channel."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding.pi.client import PiClient
from nanobot.coworker.coding.pi.questions import QuestionRouter
from nanobot.coworker.coding.runtime import SessionSpec
from nanobot.coworker.config import PiBackendConfig


@pytest.mark.asyncio
async def test_run_prompt_handles_rejection(tmp_path: Path) -> None:
    cfg = PiBackendConfig(allow_unsandboxed=True)
    client = PiClient(cfg)

    with patch.object(client, "_preflight", new_callable=AsyncMock):
        with patch.object(client, "_handshake", new_callable=AsyncMock):
            with patch.object(client.channel, "start", new_callable=AsyncMock):
                with patch.object(client.channel, "send", new_callable=AsyncMock):
                    await client.start(cwd=tmp_path, session=SessionSpec(task_id="t1"))

                    # Simulate rejected response
                    async def _fake_records():
                        yield {
                            "id": list(client._pending_requests.keys())[0] if client._pending_requests else "req1",
                            "type": "response",
                            "command": "prompt",
                            "success": False,
                            "error": "Model busy",
                        }

                    client.channel.records = _fake_records
                    client._reader_task = asyncio.create_task(client._read_loop())

                    outcome = await client.run_prompt("Do work")
                    assert outcome.status == "error"
                    assert outcome.error == "Model busy"

                    await client.close()


@pytest.mark.asyncio
async def test_run_prompt_handles_handled_disposition(tmp_path: Path) -> None:
    cfg = PiBackendConfig(allow_unsandboxed=True)
    client = PiClient(cfg)

    with patch.object(client, "_preflight", new_callable=AsyncMock):
        with patch.object(client, "_handshake", new_callable=AsyncMock):
            with patch.object(client.channel, "start", new_callable=AsyncMock):
                with patch.object(client.channel, "send", new_callable=AsyncMock):
                    await client.start(cwd=tmp_path, session=SessionSpec(task_id="t2"))

                    async def _fake_records():
                        req_id = list(client._pending_requests.keys())[0]
                        yield {
                            "id": req_id,
                            "type": "response",
                            "command": "prompt",
                            "success": True,
                            "data": {"disposition": "handled"},
                        }

                    client.channel.records = _fake_records
                    client._reader_task = asyncio.create_task(client._read_loop())

                    outcome = await client.run_prompt("Quick turn")
                    assert outcome.status == "handled"

                    await client.close()


@pytest.mark.asyncio
async def test_extension_ui_request_roundtrip(tmp_path: Path) -> None:
    router = QuestionRouter()
    cfg = PiBackendConfig(allow_unsandboxed=True)
    client = PiClient(cfg, question_router=router)

    sent_records: list[dict[str, Any]] = []

    async def fake_send(rec: dict[str, Any]):
        sent_records.append(rec)

    with patch.object(client, "_preflight", new_callable=AsyncMock):
        with patch.object(client, "_handshake", new_callable=AsyncMock):
            with patch.object(client.channel, "start", new_callable=AsyncMock):
                with patch.object(client.channel, "send", side_effect=fake_send):
                    await client.start(cwd=tmp_path, session=SessionSpec(task_id="t-ask"))

                    async def _fake_records():
                        # Emit an extension_ui_request
                        yield {
                            "type": "extension_ui_request",
                            "id": "ui-req-1",
                            "method": "input",
                            "title": "nanobot:ask:architecture_choice",
                            "message": "Which design should we follow?",
                        }
                        await asyncio.sleep(0.1)

                    client.channel.records = _fake_records
                    client._reader_task = asyncio.create_task(client._read_loop())

                    await asyncio.sleep(0.02)
                    pending = router.get_pending("ui-req-1")
                    assert pending is not None
                    assert pending.blocking_reason == "architecture_choice"
                    assert len(router.list_pending_for_task("t-ask")) == 1

                    ok = router.answer_question("ui-req-1", "Design Pattern B")
                    assert ok is True

                    await asyncio.sleep(0.02)
                    assert any(
                        r.get("type") == "extension_ui_response"
                        and r.get("id") == "ui-req-1"
                        and r.get("value") == "Design Pattern B"
                        for r in sent_records
                    )
                    assert len(router.list_pending_for_task("t-ask")) == 0

                    await client.close()


@pytest.mark.asyncio
async def test_preflight_and_handshake_checks(tmp_path: Path) -> None:
    cfg = PiBackendConfig(allow_unsandboxed=True, min_version="99.0.0")
    client = PiClient(cfg)
    with patch("nanobot.coworker.coding.pi.client.check_pi_version", return_value=False):
        with pytest.raises(RuntimeError, match="does not satisfy minimum required version"):
            await client.start(cwd=tmp_path, session=SessionSpec(task_id="t3"))

    cfg_ok = PiBackendConfig(allow_unsandboxed=True, min_version="1.0.0")
    client_ok = PiClient(cfg_ok)
    with patch.object(client_ok, "_preflight", new_callable=AsyncMock):
        with patch.object(client_ok.channel, "start", new_callable=AsyncMock):
            with patch.object(client_ok, "request", new_callable=AsyncMock) as mock_req:
                from nanobot.coworker.coding.pi.protocol import Response

                mock_req.return_value = Response(
                    id="1", type="response", command="get_commands", success=True, data={"commands": []}
                )
                with pytest.raises(RuntimeError, match="nanobot-mode command missing"):
                    await client_ok._handshake(extension=Path("fake-ext.ts"))
