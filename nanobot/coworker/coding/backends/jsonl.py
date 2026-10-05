"""Strict JSONL streaming and process group management helpers."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.coworker.transcript import as_dict


def parse_jsonl_line(raw: bytes) -> dict[str, Any] | None:
    """Parse one JSONL line safely.

    Strict framing: split on \n only, strip trailing \r, never split on U+2028/U+2029.
    Malformed or non-dict lines return None.
    """
    line = raw.rstrip(b"\n")
    if line.endswith(b"\r"):
        line = line[:-1]
    if not line:
        return None
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        return None
    try:
        val = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return as_dict(val)


async def iter_jsonl_stream(
    reader: asyncio.StreamReader,
    *,
    limit: int = 16 * 1024 * 1024,
) -> AsyncIterator[dict[str, Any]]:
    """Yield parsed JSON objects from an asyncio StreamReader line by line."""
    while True:
        try:
            line = await reader.readuntil(b"\n")
        except asyncio.IncompleteReadError as e:
            if e.partial:
                parsed = parse_jsonl_line(e.partial)
                if parsed is not None:
                    yield parsed
            break
        except asyncio.LimitOverrunError as e:
            # The line exceeded reader's internal limit. Skip chunks until \n is reached.
            discarded_chunks: list[bytes] = []
            try:
                # Read out the consumed buffer chunk
                if hasattr(e, "consumed") and e.consumed > 0:
                    chunk = await reader.readexactly(e.consumed)
                    if chunk:
                        discarded_chunks.append(chunk)
                while True:
                    try:
                        chunk = await reader.readuntil(b"\n")
                        discarded_chunks.append(chunk)
                        break
                    except asyncio.LimitOverrunError as inner_e:
                        if hasattr(inner_e, "consumed") and inner_e.consumed > 0:
                            chunk = await reader.readexactly(inner_e.consumed)
                            if chunk:
                                discarded_chunks.append(chunk)
                        else:
                            break
                    except (asyncio.IncompleteReadError, EOFError):
                        break
            except Exception:
                pass
            discarded = b"".join(discarded_chunks)
            yield {
                "type": "__jsonl_overrun__",
                "error": "JSONL record exceeded stream limit",
                "raw_line": (discarded[:1000].decode("utf-8", errors="replace")) if discarded else None,
            }
            continue
        except EOFError:
            break

        parsed = parse_jsonl_line(line)
        if parsed is not None:
            yield parsed


DEFAULT_STREAM_LIMIT = 64 * 1024 * 1024  # 64 MB


class StderrRingBuffer:
    """Bounded in-memory ring buffer holding the most recent stderr bytes."""

    def __init__(self, max_bytes: int = 256 * 1024) -> None:
        self.max_bytes = max_bytes
        self._chunks: list[bytes] = []
        self._total_bytes: int = 0

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        if len(chunk) >= self.max_bytes:
            self._chunks = [chunk[-self.max_bytes:]]
            self._total_bytes = self.max_bytes
            return
        self._chunks.append(chunk)
        self._total_bytes += len(chunk)
        while self._chunks and self._total_bytes - len(self._chunks[0]) >= self.max_bytes:
            self._total_bytes -= len(self._chunks.pop(0))

    def get_text(self, encoding: str = "utf-8", errors: str = "replace") -> str:
        data = b"".join(self._chunks)
        if len(data) > self.max_bytes:
            data = data[-self.max_bytes:]
        return data.decode(encoding, errors=errors)


async def drain_stderr_to_buffer(
    reader: asyncio.StreamReader,
    buffer: StderrRingBuffer,
) -> None:
    """Continuously read reader until EOF and store in ring buffer."""
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            buffer.feed(chunk)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug(f"Error draining stderr: {exc}")


async def spawn_process_group(
    args: list[str],
    *,
    cwd: Path | str,
    env: dict[str, str],
    stdin_pipe: bool = True,
    limit: int = DEFAULT_STREAM_LIMIT,
) -> asyncio.subprocess.Process:
    """Spawn a subprocess in a new process group for clean subtree termination."""
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin_pipe else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=limit,
        start_new_session=True,
    )


async def terminate_process_group(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float = 5.0,
) -> None:
    """Terminate a process and its whole process group (SIGTERM, then wait, then SIGKILL)."""
    if proc.returncode is not None:
        return

    if os.name == "nt":
        # No process groups on Windows. Closing a ``wsl.exe`` relay ends the Linux side too
        # (``bwrap --die-with-parent``); native children are killed with the tree below.
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
        return

    pid = proc.pid
    try:
        pgid = os.getpgid(pid)
    except ProcessLookupError:
        return

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as e:
        logger.debug(f"Failed to SIGTERM process group {pgid}: {e}")

    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except (asyncio.TimeoutError, TimeoutError):
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as e:
            logger.debug(f"Failed to SIGKILL process group {pgid}: {e}")
        try:
            await proc.wait()
        except Exception:
            pass
