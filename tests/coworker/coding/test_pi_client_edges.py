"""Tests for PiClient using mocked channel."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding.pi.client import PiClient
from nanobot.coworker.coding.runtime import SessionSpec
from nanobot.coworker.config import PiBackendConfig


@pytest.mark.asyncio
async def test_run_prompt_handles_rejection(tmp_path: Path) -> None:
    cfg = PiBackendConfig(allow_unsandboxed=True)
    client = PiClient(cfg)

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
