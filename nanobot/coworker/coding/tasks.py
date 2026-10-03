"""Coding task model, state persistence, and registry."""

from __future__ import annotations

import json
import os
import random
import string
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from loguru import logger

TaskStatus = Literal[
    "started",
    "running",
    "succeeded",
    "failed_acceptance",
    "aborted",
    "timed_out",
    "error",
    "interrupted",
]


def generate_task_id() -> str:
    """Generate id in format ct-YYYYMMDD-HHMMSS-xxxx."""
    now_str = time.strftime("%Y%m%d-%H%M%S")
    rand_suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"ct-{now_str}-{rand_suffix}"


@dataclass
class CodingTask:
    id: str
    backend: str
    session_key: str
    channel: str
    chat_id: str
    repo: str
    base: str
    branch: str
    worktree: str
    brief: str
    acceptance: str | None = None
    status: TaskStatus = "started"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    resume_ref: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    round_stats: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    diffstat: str = ""
    commits: list[str] = field(default_factory=list)
    acceptance_output: str | None = None
    error: str | None = None
    raw_error_line: str | None = None
    # Live progress for the WebUI (tool_count, last_tool, last_event_at, rounds); the registry keeps
    # the same object in memory, so mutating it is visible to status without a disk write per event.
    live: dict[str, Any] = field(default_factory=dict)
    # Project directory relative to the git toplevel when the user picked a subdirectory
    # (monorepo); the harness and acceptance command run there, git operations at the root.
    subdir: str = ""
    # ``direct`` tasks edit a non-git project in place (no branch, no worktree): ``workdir`` is the
    # project, ``snapshot`` the pre-run copy/manifest used for diff and undo, ``changes`` what changed.
    mode: Literal["worktree", "direct"] = "worktree"
    workdir: str = ""
    snapshot: str = ""
    changes: dict[str, list[str]] = field(default_factory=dict)
    # Files changed outside the project while the task ran ("+ added", "~ modified", "- deleted").
    outside_writes: list[str] = field(default_factory=list)
    finished_at: float = 0.0

    @property
    def run_dir(self) -> Path:
        """Directory the harness runs in: the project (direct), or the worktree / its subdirectory."""
        if self.mode == "direct":
            return Path(self.workdir)
        base = Path(self.worktree)
        return base / self.subdir if self.subdir else base

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodingTask:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class TaskRegistry:
    """Persistent storage for coding tasks under <workspace>/.coworker/coding-tasks/."""

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root
        self.tasks_dir = workspace_root / ".coworker" / "coding-tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, CodingTask] = {}
        self._load_and_recover()

    def _load_and_recover(self) -> None:
        """Load saved tasks and mark any previously running tasks as interrupted."""
        if not self.tasks_dir.exists():
            return

        for fpath in self.tasks_dir.glob("ct-*.json"):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                task = CodingTask.from_dict(data)
                # Restart recovery: mark in-flight tasks as interrupted
                if task.status in ("started", "running"):
                    logger.info(f"Marking interrupted task: {task.id}")
                    task.status = "interrupted"
                    task.updated_at = time.time()
                    self.save(task)
                self._memory_cache[task.id] = task
            except Exception as e:
                logger.warning(f"Failed loading coding task from {fpath}: {e}")

    def save(self, task: CodingTask) -> None:
        task.updated_at = time.time()
        self._memory_cache[task.id] = task

        target = self.tasks_dir / f"{task.id}.json"
        tmp_target = self.tasks_dir / f"{task.id}.json.tmp"
        try:
            content = json.dumps(task.to_dict(), ensure_ascii=False, indent=2)
            tmp_target.write_text(content, encoding="utf-8")
            os.replace(tmp_target, target)
        except Exception as e:
            logger.error(f"Failed saving task {task.id}: {e}")
            if tmp_target.exists():
                tmp_target.unlink(missing_ok=True)

    def get(self, task_id: str) -> CodingTask | None:
        return self._memory_cache.get(task_id)

    def list_tasks(self) -> list[CodingTask]:
        return sorted(self._memory_cache.values(), key=lambda t: t.created_at, reverse=True)

    def count_active_direct(self, workdir: str | Path) -> int:
        """Running ``direct`` tasks in ``workdir`` (they have no isolation, so only one may run)."""
        key = os.path.normcase(str(Path(workdir).expanduser().resolve()))
        return sum(
            1
            for t in self._memory_cache.values()
            if t.mode == "direct"
            and t.status in ("started", "running")
            and os.path.normcase(str(Path(t.workdir).expanduser().resolve())) == key
        )

    def count_active(self, session_key: str | None = None) -> int:
        return sum(
            1
            for t in self._memory_cache.values()
            if t.status in ("started", "running") and (session_key is None or t.session_key == session_key)
        )


_shared: dict[Path, TaskRegistry] = {}


def shared_registry(workspace_root: Path) -> TaskRegistry:
    """Process-wide registry per workspace.

    Constructing a ``TaskRegistry`` performs restart recovery (in-flight tasks become
    ``interrupted``), so it must happen once per process — not on every tool call, command or
    status poll — otherwise a running task is clobbered and its live progress is invisible.
    """
    key = workspace_root.expanduser().resolve()
    registry = _shared.get(key)
    if registry is None:
        registry = _shared[key] = TaskRegistry(key)
    return registry


def reset_shared_registries() -> None:
    """Test hook."""
    _shared.clear()
