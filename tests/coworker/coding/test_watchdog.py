"""Watchdog regression: PiClient declares an idle timeout when no events arrive."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding.pi.client import PiClient
from nanobot.coworker.coding.runtime import SessionSpec
from nanobot.coworker.config import PiBackendConfig


@pytest.mark.asyncio
async def test_client_idle_timeout(tmp_path: Path) -> None:
    cfg = PiBackendConfig(allow_unsandboxed=True)
    # Tiny idle window so the test does not wait a real minute.
    client = PiClient(cfg, timeout_minutes=10, idle_timeout_minutes=0.01)

    with (
        patch.object(client, "_preflight", new_callable=AsyncMock),
        patch.object(client, "_handshake", new_callable=AsyncMock),
        patch.object(client.channel, "start", new_callable=AsyncMock),
        patch.object(client.channel, "send", new_callable=AsyncMock),
    ):
        await client.start(cwd=tmp_path, session=SessionSpec(task_id="ct-idle"))

        async def _fake_records():
            req_id = next(iter(client._pending_requests))
            yield {
                "id": req_id,
                "type": "response",
                "command": "prompt",
                "success": True,
                "data": {"disposition": "started"},
            }
            await asyncio.sleep(30)  # stay silent: never emit agent_settled

        client.channel.records = _fake_records
        client._reader_task = asyncio.create_task(client._read_loop())

        with patch.object(client, "abort", new_callable=AsyncMock) as mock_abort:
            outcome = await asyncio.wait_for(client.run_prompt("Stall please"), timeout=10.0)

        assert outcome.status == "timed_out"
        assert "Idle timeout" in (outcome.error or "")
        mock_abort.assert_awaited()

        await client.close()
