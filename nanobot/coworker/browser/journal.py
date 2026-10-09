"""The browser journal: a durable record written before each start and stop (BrowserSkill Mức 2, Journal).

Each line is one event. A session is "open" from its ``start_ok`` until a ``stopped`` receipt for the same
session id. After a crash, the open sessions are the ones this process must still stop, so the journal is what
makes cleanup survive a restart. Writes are appended and fsynced; a torn last line is ignored when read.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

JOURNAL_NAME = "journal.jsonl"
EVENTS = ("start_intent", "start_ok", "start_failed", "stop_intent", "stopped")


@dataclass(frozen=True)
class OpenSession:
    session_id: str
    key: str
    agent_id: str
    request_id: str | None


class BrowserJournal:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / JOURNAL_NAME

    def append(self, event: str, **fields: Any) -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown journal event: {event}")
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {"event": event, "at": int(time.time() * 1000), **fields}
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        records: list[dict[str, Any]] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            try:
                loaded: object = json.loads(raw)
            except ValueError:
                continue  # a line torn by a crash; the events before it still count
            if isinstance(loaded, dict):
                records.append(cast("dict[str, Any]", loaded))
        return records

    def open_sessions(self) -> list[OpenSession]:
        """Sessions started and not yet stopped, in the order they were started."""
        open_by_id: dict[str, OpenSession] = {}
        for record in self.read():
            session_id = record.get("session_id")
            if not isinstance(session_id, str):
                continue
            if record.get("event") == "start_ok":
                key = record.get("key")
                agent_id = record.get("agent_id")
                request_id = record.get("request_id")
                open_by_id[session_id] = OpenSession(
                    session_id=session_id,
                    key=key if isinstance(key, str) else "",
                    agent_id=agent_id if isinstance(agent_id, str) else "main",
                    request_id=request_id if isinstance(request_id, str) else None,
                )
            elif record.get("event") == "stopped":
                open_by_id.pop(session_id, None)
        return list(open_by_id.values())
