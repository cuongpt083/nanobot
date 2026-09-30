"""``workflow_run`` and ``workflow_distill`` tools."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker.runtime import live_messages, services
from nanobot.coworker.tools_base import CoworkerTool
from nanobot.coworker.workflows import drive
from nanobot.coworker.workflows.distill import distill
from nanobot.coworker.workflows.registry import list_workflows

WORKFLOW_TOOLS = frozenset({"workflow_run", "workflow_distill"})


@tool_parameters({
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "start", "status", "cancel"],
            "description": "list = discover; start = begin a run; status = this session's run; "
            "cancel = stop this session's run (only after the user confirmed).",
        },
        "workflow": {
            "type": "string",
            "description": 'Workflow ref for start: "<slug>" or "skill:<skill>/<slug>" (exact refs from action "list").',
        },
        "input": {"type": "string", "description": "Task input for the run, shown to every step."},
    },
    "required": ["action"],
})
class WorkflowRunTool(CoworkerTool):
    @property
    def name(self) -> str:
        return "workflow_run"

    @property
    def description(self) -> str:
        return (
            "Run a registered Agent Workflow (deterministic markdown step-graph) in this session, or list them. "
            'action "start" hands control to the HARNESS: it drives you through the graph one step per turn '
            "with enforced routing — after starting, finish your current reply briefly and do NOT execute "
            "workflow steps yourself."
        )

    async def execute(self, action: str = "", workflow: str = "", input: str = "", **kwargs: Any) -> ToolResult:
        svc = services()
        session = self.session()
        if svc is None:
            return self.payload("error", error="workflow engine not bound")
        if action == "list":
            items = [
                {"ref": w.ref, "name": w.name, "description": w.description, "steps": w.steps}
                for w in list_workflows(svc.workspace)
            ]
            return self.payload("ok", workflows=items)
        if session is None:
            return self.payload("error", error="workflow runs must be bound to a session")
        try:
            if action == "status":
                return self.payload("ok", run=drive.status(session, svc.workspace))
            if action == "cancel":
                return self.payload("ok", **drive.cancel(session, svc.workspace))
            if action == "start":
                if not workflow.strip():
                    return self.payload("error", error='workflow ref required for start (see action "list")')
                started = drive.start(session, svc.workspace, workflow.strip(), input)
                return self.payload(
                    "ok",
                    **started,
                    note="Run started. The harness drives this session step by step after your reply. "
                    "Finish your current reply briefly; do NOT execute steps yourself.",
                )
        except Exception as exc:
            return self.payload("error", error=str(exc))
        return self.payload("error", error=f'unknown action "{action}" (allowed: list, start, status, cancel)')


@tool_parameters({
    "type": "object",
    "properties": {
        "slug": {"type": "string", "description": 'Short kebab-case name for the draft (e.g. "weekly-report").'},
    },
    "required": ["slug"],
})
class WorkflowDistillTool(CoworkerTool):
    @property
    def name(self) -> str:
        return "workflow_distill"

    @property
    def description(self) -> str:
        return (
            "Distill THIS session's completed work into a draft Agent Workflow (deterministic transcript "
            "segmentation, no invention): one step per work phase, written to workflows/<slug>-draft. Use when "
            'the user asks to "save this as a workflow" / "lưu những gì vừa làm thành quy trình". Afterwards, '
            "review and generalize the draft with the user before running it."
        )

    async def execute(self, slug: str = "", **kwargs: Any) -> ToolResult:
        svc = services()
        request = self.request()
        session = self.session()
        if svc is None or request is None or session is None:
            return self.payload("error", error="no active session")
        messages = live_messages(request.session_key) or list(session.messages)
        try:
            result = distill(svc.workspace, slug, messages)
        except Exception as exc:
            return self.payload("error", error=str(exc))
        return self.payload(
            "ok",
            ref=result.ref,
            dir=str(result.dir),
            steps=result.steps,
            phases=result.phases,
            validation=asdict(result.validation),
            note="Draft written. Review it with the user and generalize before running.",
        )
