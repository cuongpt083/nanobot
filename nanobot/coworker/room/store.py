"""Per-room persistence: the shared ``room_state`` scratchpad and the room transcript.

Scope is the ROOM (the owner's session), never the agent: the coordinator and
every teammate read and write the same files. Room turns are sequential, so a
tmp+rename atomic write is enough.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.coworker.transcript import as_dict, as_list

MAX_KEYS = 50
MAX_VALUE_BYTES = 32 * 1024
MAX_FILE_BYTES = 256 * 1024
MAX_TRANSCRIPT_ENTRIES = 400


def room_id_for(session_key: str) -> str:
    rid = re.sub(r"[^A-Za-z0-9._-]+", "_", session_key).strip("._-")
    return rid[:128] or "room"


def rooms_dir(workspace: Path) -> Path:
    return workspace / ".coworker" / "rooms"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _value_bytes(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return MAX_VALUE_BYTES + 1


@dataclass(frozen=True)
class RoomEntry:
    value: Any
    by: str
    at: float


class RoomStateStore:
    def __init__(self, workspace: Path, room_id: str) -> None:
        self._path = rooms_dir(workspace) / f"{room_id}.state.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            doc = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        root = as_dict(doc)
        entries = as_dict(root.get("entries")) if root is not None else None
        if entries is None:
            return {}
        return {k: e for k, raw in entries.items() if (e := as_dict(raw)) is not None}

    def _save(self, entries: dict[str, dict[str, Any]]) -> None:
        text = json.dumps({"entries": entries}, ensure_ascii=False)
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError(f"room state exceeds {MAX_FILE_BYTES} bytes — delete keys before adding more")
        _atomic_write(self._path, text)

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for key, entry in sorted(self._load().items()):
            preview = json.dumps(entry.get("value"), ensure_ascii=False)
            out.append({
                "key": key,
                "by": entry.get("by"),
                "preview": preview[:160] + ("…" if len(preview) > 160 else ""),
            })
        return out

    def get(self, key: str) -> RoomEntry | None:
        entry = self._load().get(key)
        if entry is None:
            return None
        return RoomEntry(value=entry.get("value"), by=str(entry.get("by") or ""), at=float(entry.get("at") or 0))

    def set(self, key: str, value: Any, by: str) -> RoomEntry:
        entries = self._load()
        if key not in entries and len(entries) >= MAX_KEYS:
            raise ValueError(f"room state is full ({MAX_KEYS} keys) — delete a key first")
        if _value_bytes(value) > MAX_VALUE_BYTES:
            raise ValueError(f"value too large (>{MAX_VALUE_BYTES} bytes) — store a summary or a file path")
        entries[key] = {"value": value, "by": by, "at": time.time()}
        self._save(entries)
        return RoomEntry(value=value, by=by, at=entries[key]["at"])

    def append(self, key: str, item: Any, by: str) -> int:
        entries = self._load()
        existing = entries.get(key)
        if existing is None:
            if len(entries) >= MAX_KEYS:
                raise ValueError(f"room state is full ({MAX_KEYS} keys) — delete a key first")
            items: list[Any] = []
        elif (current := as_list(existing.get("value"))) is not None:
            items = list(current)
        else:
            raise ValueError(f'key "{key}" already holds a non-list value — use set to overwrite')
        items.append(item)
        if _value_bytes(items) > MAX_VALUE_BYTES:
            raise ValueError(f"list too large (>{MAX_VALUE_BYTES} bytes) — start a new key or summarise")
        entries[key] = {"value": items, "by": by, "at": time.time()}
        self._save(entries)
        return len(items)

    def delete(self, key: str) -> bool:
        entries = self._load()
        if key not in entries:
            return False
        del entries[key]
        self._save(entries)
        return True

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)


class RoomTranscript:
    """Append-only log of delegations and teammate replies (the room's shared memory)."""

    def __init__(self, workspace: Path, room_id: str) -> None:
        self._path = rooms_dir(workspace) / f"{room_id}.transcript.jsonl"

    def append(self, speaker: str, text: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": time.time(), "speaker": speaker, "text": text}, ensure_ascii=False) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-MAX_TRANSCRIPT_ENTRIES:]:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            entry = as_dict(item)
            if entry is not None and isinstance(entry.get("text"), str):
                out.append(entry)
        return out

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
