"""Checkpoint storage for room delegation queues.

Persists active, queued, and finished delegations to ``.coworker/rooms/<room_id>.queue.json``
so room execution can survive restarts and be resumed via ``/room resume``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from nanobot.coworker.room.scheduler import Delegation
from nanobot.coworker.room.store import _atomic_write, rooms_dir

QUEUE_SCHEMA_VERSION = 1


def delegation_to_dict(d: Delegation) -> dict[str, Any]:
    return {
        "id": d.id,
        "agent_id": d.agent_id,
        "task": d.task,
        "by": d.by,
        "context": d.context,
        "context_keys": list(d.context_keys),
        "after": list(d.after),
        "deliverable": d.deliverable,
    }


def delegation_from_dict(raw: dict[str, Any]) -> Delegation:
    return Delegation(
        id=str(raw.get("id") or ""),
        agent_id=str(raw.get("agent_id") or ""),
        task=str(raw.get("task") or ""),
        by=str(raw.get("by") or "owner"),
        context=str(raw.get("context") or ""),
        context_keys=tuple(raw.get("context_keys") or ()),
        after=tuple(raw.get("after") or ()),
        deliverable=str(raw.get("deliverable") or ""),
    )


class RoomQueueStore:
    def __init__(self, workspace: Path, room_id: str) -> None:
        self.workspace = workspace
        self.room_id = room_id
        self._path = rooms_dir(workspace) / f"{room_id}.queue.json"

    def exists(self) -> bool:
        return self._path.is_file()

    def clear(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def load(self) -> dict[str, Any] | None:
        try:
            doc = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("version") == QUEUE_SCHEMA_VERSION:
                return doc
        except (OSError, ValueError):
            return None
        return None

    def save(
        self,
        *,
        session_key: str,
        channel: str,
        chat_id: str,
        chained: int,
        queued: list[Delegation],
        running: list[Delegation],
        finished: set[str] | list[str],
    ) -> None:
        data = {
            "version": QUEUE_SCHEMA_VERSION,
            "room_id": self.room_id,
            "session_key": session_key,
            "channel": channel,
            "chat_id": chat_id,
            "chained": chained,
            "queued": [delegation_to_dict(d) for d in queued],
            "running": [delegation_to_dict(d) for d in running],
            "finished": sorted(finished),
            "updated_at": time.time(),
        }
        _atomic_write(self._path, json.dumps(data, ensure_ascii=False, indent=2))

    def unfinished_delegations(self) -> list[Delegation]:
        doc = self.load()
        if not doc:
            return []
        out: list[Delegation] = []
        for raw in doc.get("running", []):
            if isinstance(raw, dict):
                out.append(delegation_from_dict(raw))
        for raw in doc.get("queued", []):
            if isinstance(raw, dict):
                out.append(delegation_from_dict(raw))
        return out
