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
        except (asyncio.LimitOverrunError, EOFError):
            break

        parsed = parse_jsonl_line(line)
        if parsed is not None:
            yield parsed


async def spawn_process_group(
    args: list[str],
    *,
    cwd: Path | str,
    env: dict[str, str],
    stdin_pipe: bool = True,
) -> asyncio.subprocess.Process:
    """Spawn a subprocess in a new process group for clean subtree termination."""
    return await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd),
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin_pipe else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
