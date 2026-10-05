"""Regression test for C3: Subprocess flooding stderr while emitting events."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from nanobot.coworker.coding.backends.jsonl import (
    StderrRingBuffer,
    drain_stderr_to_buffer,
    iter_jsonl_stream,
    spawn_process_group,
    terminate_process_group,
)


@pytest.mark.asyncio
async def test_stderr_flood_does_not_deadlock(tmp_path: Path) -> None:
    # A script writing 1 MB to stderr while writing normal events to stdout
    script = tmp_path / "flood_script.py"
    script.write_text(
        """
import sys, json

# Send 500 chunks of 2 KB = 1 MB to stderr
for _ in range(500):
    sys.stderr.write("E" * 2000 + "\\n")
    sys.stderr.flush()

# Write stdout event
sys.stdout.write(json.dumps({"type": "agent_settled"}) + "\\n")
sys.stdout.flush()
""",
        encoding="utf-8",
    )

    proc = await spawn_process_group(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env={},
        stdin_pipe=False,
    )

    assert proc.stderr is not None
    assert proc.stdout is not None

    ring_buffer = StderrRingBuffer(max_bytes=64 * 1024)
    drain_task = asyncio.create_task(drain_stderr_to_buffer(proc.stderr, ring_buffer))

    events = []
    async for item in iter_jsonl_stream(proc.stdout):
        events.append(item)

    await proc.wait()
    drain_task.cancel()
    await terminate_process_group(proc)

    # Process shouldn't deadlock, event received
    assert len(events) == 1
    assert events[0].get("type") == "agent_settled"

    # Ring buffer captured tail of stderr
    captured = ring_buffer.get_text()
    assert len(captured) <= 64 * 1024
    assert "E" in captured
