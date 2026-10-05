"""Persistent per-room thread store for coworker agents.

Stored at:
    .coworker/agents/<agent_id>/threads/<room_id>.jsonl
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

from nanobot.coworker.transcript import as_dict

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
MAX_STORE_CHARS = 4000

# Process-level thread lock per resolved path to avoid concurrent write races.
_PATH_LOCKS: dict[str, threading.Lock] = {}
_GLOBAL_LOCK = threading.Lock()


def _get_path_lock(path: Path) -> threading.Lock:
    resolved = str(path.resolve())
    with _GLOBAL_LOCK:
        lock = _PATH_LOCKS.get(resolved)
        if lock is None:
            lock = threading.Lock()
            _PATH_LOCKS[resolved] = lock
        return lock


def _sanitize_component(val: str, label: str) -> str:
    cleaned = val.strip()
    if not cleaned or not _SAFE_ID.match(cleaned) or ".." in cleaned:
        raise ValueError(f"Invalid {label}: {val!r}")
    return cleaned


def agent_threads_dir(workspace: Path, agent_id: str) -> Path:
    safe_agent = _sanitize_component(agent_id, "agent_id")
    return workspace.resolve() / ".coworker" / "agents" / safe_agent / "threads"


class AgentThreadStore:
    """.coworker/agents/<agent_id>/threads/<room_id>.jsonl — each line is a completed turn."""

    def __init__(self, workspace: Path, agent_id: str, room_id: str) -> None:
        safe_room = _sanitize_component(room_id, "room_id")
        self._dir = agent_threads_dir(workspace, agent_id)
        self._path = self._dir / f"{safe_room}.jsonl"
        self._lock = _get_path_lock(self._path)

    @property
    def path(self) -> Path:
        return self._path

    def recent(self, max_turns: int) -> list[dict[str, str]]:
        """Return history formatted as alternating user/assistant message dicts."""
        if max_turns <= 0:
            return []
        try:
            with self._lock:
                lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []

        entries: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            entry = as_dict(item)
            if entry is not None and isinstance(entry.get("task"), str) and isinstance(entry.get("reply"), str):
                entries.append(entry)

        selected = entries[-max_turns:]
        messages: list[dict[str, str]] = []
        for entry in selected:
            messages.append({"role": "user", "content": entry["task"]})
            messages.append({"role": "assistant", "content": entry["reply"]})
        return messages

    def append_turn(
        self,
        *,
        task: str,
        reply: str,
        tools_used: list[str] | None = None,
        usage: dict[str, int] | None = None,
        at: float | None = None,
    ) -> None:
        truncated_task = task[:MAX_STORE_CHARS]
        truncated_reply = reply[:MAX_STORE_CHARS]
        record: dict[str, Any] = {
            "at": at if at is not None else time.time(),
            "task": truncated_task,
            "reply": truncated_reply,
            "tools_used": tools_used or [],
            "usage": usage or {},
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)

    def clear(self) -> None:
        with self._lock:
            self._path.unlink(missing_ok=True)


def clear_room_threads(workspace: Path, room_id: str) -> None:
    """Clear all agent thread files for a given room_id across all agents."""
    safe_room = _sanitize_component(room_id, "room_id")
    agents_root = workspace.resolve() / ".coworker" / "agents"
    if not agents_root.is_dir():
        return
    for agent_dir in agents_root.iterdir():
        if not agent_dir.is_dir():
            continue
        thread_file = agent_dir / "threads" / f"{safe_room}.jsonl"
        if thread_file.is_file():
            lock = _get_path_lock(thread_file)
            with lock:
                thread_file.unlink(missing_ok=True)
