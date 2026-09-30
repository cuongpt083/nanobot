"""Distill — "save this session's work as a workflow draft".

Deterministic scaffold (no LLM pass): segment the transcript into phases, one
per genuine user turn, with the tools the agent actually used, and write a
linear draft workflow the user/agent then generalizes. The review of the draft
IS the training step.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nanobot.coworker.transcript import is_genuine_user, message_text, tool_call_name, tool_calls
from nanobot.coworker.workflows.format import Validation, load_workflow, validate_workflow
from nanobot.coworker.workflows.registry import workflows_root

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_NON_WORK_TOOLS = frozenset({"workflow_distill", "workflow_run", "advisor", "mark_context_wasted"})


@dataclass
class Phase:
    user_text: str
    tools: Counter[str] = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DistillResult:
    dir: Path
    ref: str
    steps: int
    phases: int
    validation: Validation


def segment(messages: list[dict[str, Any]]) -> list[Phase]:
    phases: list[Phase] = []
    current: Phase | None = None
    for m in messages:
        if is_genuine_user(m):
            current = Phase(user_text=message_text(m).strip())
            phases.append(current)
        elif m.get("role") == "assistant" and current is not None:
            for call in tool_calls(m):
                name = tool_call_name(call)
                if name and name not in _NON_WORK_TOOLS:
                    current.tools[name] += 1
            note = message_text(m).strip()
            if note:
                current.notes.append(note)
    # The request that asked for the distillation is not part of the procedure.
    if phases and not phases[-1].tools and re.search(r"workflow|quy trình|quy trinh", phases[-1].user_text, re.I):
        phases.pop()
    return phases


def _step_slug(index: int, text: str) -> str:
    words = re.sub(r"[^a-z0-9\s_-]+", " ", text.lower()).split()[:4]
    base = re.sub(r"-+", "-", "-".join(words)).strip("-") or "step"
    return f"{index + 1:02d}-{base}"[:48]


def _quote(text: str) -> str:
    return "> " + text.replace("\n", "\n> ")


def _render_step(phase: Phase, next_slug: str) -> str:
    tools = ", ".join(f"{n} ×{c}" for n, c in phase.tools.most_common()) or "(no tool calls)"
    note = phase.notes[-1] if phase.notes else ""
    if len(note) > 600:
        note = note[:600] + "…"
    lines = [
        "---", "type: task", "---", "",
        "<!-- DRAFT distilled from a real session. Generalize before use: replace run-specific values",
        "     with placeholders, tighten the instruction, and add an ## Output schema for the data contract. -->",
        "", "Original instruction in the source run:", "", _quote(phase.user_text), "",
        f"Tools the agent actually used for this phase: {tools}",
    ]
    if note:
        lines += ["", "How the agent concluded this phase (excerpt):", "", _quote(note)]
    lines += ["", "## Next", f"- [[{next_slug}]]", ""]
    return "\n".join(lines)


def distill(workspace: Path, slug: str, messages: list[dict[str, Any]]) -> DistillResult:
    slug = slug.strip().lower()
    if not _SLUG.fullmatch(slug):
        raise ValueError("slug must be short kebab-case: [a-z0-9-], max 48 chars")
    phases = segment(messages)
    if not phases:
        raise ValueError("no distillable phases found (no genuine user turns with work in this session)")
    draft = f"{slug}-draft"
    directory = workflows_root(workspace) / draft
    if directory.exists():
        raise FileExistsError(f"draft already exists: {directory} — pick another slug or delete it first")
    steps_dir = directory / "steps"
    steps_dir.mkdir(parents=True)
    slugs = [_step_slug(i, p.user_text) for i, p in enumerate(phases)]
    for i, phase in enumerate(phases):
        next_slug = slugs[i + 1] if i + 1 < len(phases) else "finish"
        (steps_dir / f"{slugs[i]}.md").write_text(_render_step(phase, next_slug), encoding="utf-8")
    (steps_dir / "finish.md").write_text(
        "---\ntype: end\ntitle: Finish\n---\n\nSummarize the run result for the user.\n", encoding="utf-8"
    )
    (directory / "workflow.md").write_text(
        "\n".join([
            "---",
            f"name: {draft}",
            "description: DRAFT distilled from a session run — review and generalize before first use",
            f'start: "[[{slugs[0]}]]"',
            "---",
            "",
            "Draft workflow distilled from a real session. Rewrite step bodies into reusable instructions,",
            "add decisions/parallel branches where the linear chain oversimplifies, then run it.",
            "",
        ]),
        encoding="utf-8",
    )
    wf = load_workflow(directory)
    return DistillResult(
        dir=directory,
        ref=draft,
        steps=len(wf.steps),
        phases=len(phases),
        validation=validate_workflow(wf),
    )
