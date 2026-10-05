"""Regression test: Watchdog unblocks PiRun via abort -> terminate -> read_loop finally."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from nanobot.coworker.coding.backends.pi import PiBackend
from nanobot.coworker.config import PiBackendConfig


@pytest.mark.asyncio
async def test_watchdog_unblocks_pirun_via_abort(tmp_path: Path) -> None:
    # A fake pi script that just sleeps forever without outputting any JSONL
    silent_script = tmp_path / "silent_pi.py"
    silent_script.write_text(
        """
import time, sys
# Stay alive silently until terminated
time.sleep(30)
""",
        encoding="utf-8",
    )

    cfg = PiBackendConfig(
        command=[sys.executable, str(silent_script)],
        allow_unsandboxed=True,
    )
    backend = PiBackend(cfg, global_sandbox="none")

    run = backend.start(
        brief="Test silent abort",
        cwd=tmp_path,
        rules="",
        task_id="ct-silent-test",
    )

    # In a background task, simulate watchdog aborting after 0.5s
    async def _abort_soon():
        await asyncio.sleep(0.5)
        await backend.abort()

    abort_task = asyncio.create_task(_abort_soon())

    # We consume events from run. It MUST unblock and terminate, not hang forever!
    events = []
    try:
        async for event in run:
            events.append(event)
    finally:
        await abort_task

    assert len(events) >= 1
    # Check that error event was produced when process terminated
    assert any(getattr(e, "error", None) is not None for e in events)
    assert backend.proc is not None
    assert backend.proc.returncode is not None
