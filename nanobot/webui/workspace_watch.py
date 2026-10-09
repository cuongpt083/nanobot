"""Files open in the editor, and the changes made to them on disk (Phase 8, fs.changed).

The editor reports which project files its tabs show (``session.workspace.tabs``). The runtime polls those files
every ``POLL_INTERVAL_S`` seconds: a file whose size or modification time moved is reported to the WebUI clients,
which re-read it. Polling a few open files is cheap and needs no platform file-watch API.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

POLL_INTERVAL_S = 2.0
EVENT_NAME = "workspace_changed"

# (mtime_ns, size) per open file; None when the file is missing.
Stamp = tuple[int, int] | None


@dataclass
class OpenFiles:
    """The files each session has open: session key → (project root, relative paths)."""

    _sessions: dict[str, tuple[str, frozenset[str]]] = field(default_factory=dict)

    def set(self, session_key: str, root: Path, paths: Iterable[str]) -> None:
        cleaned = frozenset(p for p in paths if p and not p.startswith("/") and ".." not in Path(p).parts)
        if cleaned:
            self._sessions[session_key] = (str(root), cleaned)
        else:
            self._sessions.pop(session_key, None)

    def items(self) -> list[tuple[str, Path, frozenset[str]]]:
        return [(key, Path(root), paths) for key, (root, paths) in self._sessions.items()]


open_files = OpenFiles()


def stamp(root: Path, rel: str) -> Stamp:
    try:
        info = (root / rel).stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


@dataclass(frozen=True)
class Change:
    session_key: str
    path: str


def poll(
    previous: dict[str, dict[str, Stamp]],
    registry: OpenFiles,
) -> tuple[list[Change], dict[str, dict[str, Stamp]]]:
    """Compare the open files now with the stamps from the last poll. Returns the changes and the new stamps."""
    current: dict[str, dict[str, Stamp]] = {}
    changes: list[Change] = []
    for session_key, root, paths in registry.items():
        now = {rel: stamp(root, rel) for rel in sorted(paths)}
        current[session_key] = now
        before = previous.get(session_key)
        if before is None:
            continue  # first sight of these files: nothing to compare against yet
        for rel, value in now.items():
            if before.get(rel, value) != value:
                changes.append(Change(session_key=session_key, path=rel))
    return changes, current


def event_body(change: Change) -> str:
    return json.dumps({"event": EVENT_NAME, "session_key": change.session_key, "path": change.path}, ensure_ascii=False)


async def deliver(
    changes: Iterable[Change],
    connections: Iterable[Any],
    send: Callable[[Any, str], Awaitable[None]],
) -> int:
    """Send each change to every WebUI connection. Returns how many frames were sent."""
    frames = [event_body(change) for change in changes]
    sent = 0
    targets = list(connections)
    for frame in frames:
        for connection in targets:
            await send(connection, frame)
            sent += 1
    return sent
