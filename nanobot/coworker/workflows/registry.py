"""Workflow discovery and run persistence.

Workflows live in ``<workspace>/workflows/<slug>/`` (ref ``<slug>``) or inside a
skill at ``<workspace>/skills/<skill>/workflows/<slug>/`` (ref
``skill:<skill>/<slug>``). Runs are stored under
``<workspace>/.coworker/workflow-runs/<slug>/<run-id>/`` as ``run.json`` plus an
append-only ``trace.jsonl``.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.coworker.transcript import as_dict
from nanobot.coworker.workflows.engine import RunState
from nanobot.coworker.workflows.format import load_workflow

_REF = re.compile(r"^(?:skill:([A-Za-z0-9._-]+)/)?([A-Za-z0-9._-]+)$")


@dataclass(frozen=True)
class WorkflowListing:
    ref: str
    name: str
    description: str
    steps: int
    dir: Path


def workflows_root(workspace: Path) -> Path:
    return workspace / "workflows"


def resolve_ref(workspace: Path, ref: str) -> Path:
    match = _REF.match(ref.strip())
    if not match:
        raise ValueError(f'invalid workflow ref "{ref}" (use "<slug>" or "skill:<skill>/<slug>")')
    skill, slug = match.groups()
    base = workspace / "skills" / skill / "workflows" if skill else workflows_root(workspace)
    directory = base / slug
    if not (directory / "workflow.md").is_file():
        raise FileNotFoundError(f'workflow "{ref}" not found (expected {directory}/workflow.md)')
    return directory


def list_workflows(workspace: Path) -> list[WorkflowListing]:
    candidates: list[tuple[str, Path]] = []
    root = workflows_root(workspace)
    if root.is_dir():
        candidates += [(d.name, d) for d in sorted(root.iterdir()) if (d / "workflow.md").is_file()]
    skills = workspace / "skills"
    if skills.is_dir():
        for skill in sorted(skills.iterdir()):
            wf_dir = skill / "workflows"
            if wf_dir.is_dir():
                candidates += [
                    (f"skill:{skill.name}/{d.name}", d)
                    for d in sorted(wf_dir.iterdir())
                    if (d / "workflow.md").is_file()
                ]
    out: list[WorkflowListing] = []
    for ref, directory in candidates:
        try:
            wf = load_workflow(directory)
            out.append(WorkflowListing(ref, wf.name, wf.description, len(wf.steps), directory))
        except Exception as exc:
            out.append(WorkflowListing(ref, directory.name, f"LOAD ERROR: {exc}", 0, directory))
    return out


def new_run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid() % 1000:03d}{time.time_ns() % 1000:03d}"


class RunStore:
    def __init__(self, workspace: Path, workflow_slug: str, run_id: str) -> None:
        self.dir = workspace / ".coworker" / "workflow-runs" / workflow_slug / run_id

    def load(self) -> RunState:
        data = as_dict(json.loads((self.dir / "run.json").read_text(encoding="utf-8")))
        if data is None:
            raise ValueError(f"{self.dir / 'run.json'} is not a run record")
        return RunState.from_dict(data)

    def save(self, run: RunState, events: list[dict[str, Any]] | None = None) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / "run.json"
        tmp = target.with_name(f"run.json.tmp.{time.time_ns()}")
        tmp.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        if events:
            self.trace(events)

    def trace(self, events: list[dict[str, Any]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with (self.dir / "trace.jsonl").open("a", encoding="utf-8") as fh:
            for event in events:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
