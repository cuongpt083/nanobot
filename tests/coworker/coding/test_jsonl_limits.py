"""Regression test for C1: JSONL lines exceeding stream buffer limits."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nanobot.coworker.coding.backends.jsonl import (
    iter_jsonl_stream,
    spawn_process_group,
    terminate_process_group,
)


@pytest.mark.asyncio
async def test_jsonl_line_large_and_overrun(tmp_path: Path) -> None:
    # A script that produces:
    # 1. A 5 KB valid JSON line
    # 2. A 30 KB line that will overrun a 10 KB stream limit
    # 3. A normal settlement event afterwards
    script = tmp_path / "stream_producer.py"
    script.write_text(
        """
import sys, json

# 1. 5 KB line
payload_5k = {"type": "event", "data": "A" * 5000}
sys.stdout.write(json.dumps(payload_5k) + "\\n")
sys.stdout.flush()

# 2. 30 KB line (exceeds a 10 KB limit)
payload_30k = {"type": "event", "data": "B" * 30000}
sys.stdout.write(json.dumps(payload_30k) + "\\n")
sys.stdout.flush()

# 3. Valid trailing event
sys.stdout.write(json.dumps({"type": "agent_settled"}) + "\\n")
sys.stdout.flush()
""",
        encoding="utf-8",
    )

    # Spawn with a 10 KB limit to trigger LimitOverrunError on line 2
    proc = await spawn_process_group(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env={},
        stdin_pipe=False,
        limit=10 * 1024,
    )

    events = []
    assert proc.stdout is not None
    async for item in iter_jsonl_stream(proc.stdout, limit=10 * 1024):
        events.append(item)

    await terminate_process_group(proc)

    # We should receive:
    # 1. The 5k event
    # 2. The __jsonl_overrun__ error event
    # 3. The agent_settled event (proving stream didn't break or hang!)
    assert len(events) == 3
    assert events[0].get("type") == "event"
    assert len(events[0]["data"]) == 5000
    assert events[1].get("type") == "__jsonl_overrun__"
    assert events[2].get("type") == "agent_settled"
