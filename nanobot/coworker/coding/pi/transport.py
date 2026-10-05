"""Pi JSONL transport channel handling subprocess I/O."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.coworker.coding.backends.jsonl import (
    DEFAULT_STREAM_LIMIT,
    StderrRingBuffer,
    drain_stderr_to_buffer,
    spawn_process_group,
    terminate_process_group,
)


class JsonlChannel:
    """Manages child process stdout/stdin JSONL framing and concurrent stderr draining."""

    def __init__(self, *, max_record_bytes: int = DEFAULT_STREAM_LIMIT) -> None:
        self.max_record_bytes = max_record_bytes
        self.proc: asyncio.subprocess.Process | None = None
        self.stderr_buffer = StderrRingBuffer()
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()

    async def start(self, argv: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        self.proc = await spawn_process_group(
            argv,
            cwd=cwd,
            env=env,
            stdin_pipe=True,
            limit=self.max_record_bytes,
        )
        if self.proc.stderr:
            self._stderr_task = asyncio.create_task(
                drain_stderr_to_buffer(self.proc.stderr, self.stderr_buffer)
            )

    async def send(self, record: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin or self.proc.returncode is not None:
            raise RuntimeError("JsonlChannel process is not running")

        payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        async with self._write_lock:
            self.proc.stdin.write(payload)
            await self.proc.stdin.drain()

    async def records(self) -> AsyncIterator[dict[str, Any]]:
        """Yield JSON records from stdout chunk by chunk (LF-delimited)."""
        if not self.proc or not self.proc.stdout:
            return

        buffer = bytearray()
        while True:
            chunk = await self.proc.stdout.read(65536)
            if not chunk:
                break
            buffer.extend(chunk)

            while True:
                idx = buffer.find(b"\n")
                if idx == -1:
                    if len(buffer) > self.max_record_bytes:
                        logger.warning(
                            f"Discarding oversized JSONL chunk ({len(buffer)} bytes > {self.max_record_bytes})"
                        )
                        buffer.clear()
                    break

                raw_line = bytes(buffer[:idx])
                del buffer[: idx + 1]

                if raw_line.endswith(b"\r"):
                    raw_line = raw_line[:-1]
                if not raw_line:
                    continue

                try:
                    text = raw_line.decode("utf-8")
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        yield parsed
                except Exception as e:
                    logger.debug(f"Failed parsing stdout JSONL record: {e}")

        # Final leftover if any
        if buffer:
            try:
                line = bytes(buffer).rstrip(b"\r\n")
                if line:
                    parsed = json.loads(line.decode("utf-8"))
                    if isinstance(parsed, dict):
                        yield parsed
            except Exception:
                pass

    @property
    def stderr_tail(self) -> str:
        return self.stderr_buffer.get_text()

    async def close(self, *, grace: float = 5.0) -> int | None:
        if not self.proc:
            return None

        if self.proc.stdin and not self.proc.stdin.is_closing():
            try:
                self.proc.stdin.close()
            except Exception:
                pass

        try:
            await asyncio.wait_for(self.proc.wait(), timeout=grace)
        except (asyncio.TimeoutError, TimeoutError):
            await terminate_process_group(self.proc, timeout=grace)

        if self._stderr_task and not self._stderr_task.done():
            try:
                await asyncio.wait_for(self._stderr_task, timeout=1.0)
            except Exception:
                self._stderr_task.cancel()

        return self.proc.returncode
