"""The coding_agent tool exposing external harness delegation to the agent."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.runtime import services, spawn_background
from nanobot.coworker.tools_base import CoworkerTool

CODING_TOOL = "coding_agent"
DIFF_MAX_CHARS = 20_000


@tool_parameters({
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["start", "status", "steer", "abort", "result", "diff"],
            "description": "Action to perform: start, status, steer, abort, result, or diff "
            "(read the task's full code diff, e.g. before asking the advisor to review it).",
        },
        "task": {
            "type": "string",
            "description": "Clear, self-contained coding objective and requirements (required for 'start').",
        },
        "backend": {
            "type": "string",
            "enum": ["pi", "agy"],
            "description": "Coding backend ('pi' or 'agy'). Defaults to repo or global config.",
        },
        "repo": {
            "type": "string",
            "description": "Path of the repository. Optional if only one repo is configured.",
        },
        "base": {
            "type": "string",
            "description": "Git base reference (branch/commit). Defaults to repo base_ref.",
        },
        "acceptance": {
            "type": "string",
            "description": "Command to run to verify acceptance (e.g. 'pytest -q'). Defaults to repo acceptance.",
        },
        "files": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional list of relevant files to hint to the harness.",
        },
        "wait": {
            "type": "boolean",
            "description": "If true, blocks until completion and returns result inline. Only allowed for fast tasks (timeout <= 10 min).",
        },
        "id": {
            "type": "string",
            "description": "Task ID (ct-...) for status, steer, abort, result, or diff.",
        },
        "message": {
            "type": "string",
            "description": "Message to send for the 'steer' action (Pi only).",
        },
    },
    "required": ["action"],
})
class CodingAgentTool(CoworkerTool):
    """Delegate coding work to an external harness (Pi, agy) running in a git worktree."""

    @property
    def name(self) -> str:
        return CODING_TOOL

    @property
    def description(self) -> str:
        return (
            "Delegate multi-file coding, refactoring, or bug fixes with an acceptance test loop "
            "to an external coding harness (Pi or agy) running in an isolated git worktree."
        )

    def _get_runner(self) -> CodingRunner:
        svc = services()
        ws_root = svc.workspace if svc is not None else Path.cwd()
        cfg = load_coworker_config()
        return CodingRunner(cfg, ws_root)

    async def execute(
        self,
        action: str,
        task: str | None = None,
        backend: str | None = None,
        repo: str | None = None,
        base: str | None = None,
        acceptance: str | None = None,
        files: list[str] | None = None,
        wait: bool = False,
        id: str | None = None,
        message: str | None = None,
        **extra: Any,
    ) -> ToolResult:
        runner = self._get_runner()
        act = action.strip().lower()

        if act == "start":
            if not task or not task.strip():
                return self.payload("error", error="The 'task' parameter is required for 'start'.")

            req = self.request()
            session_key = (req.session_key if req and req.session_key else None) or "default"
            channel = (req.channel if req and req.channel else None) or "cli"
            chat_id = (req.chat_id if req and req.chat_id else None) or "user"

            try:
                task_obj, backend_obj, repo_cfg = runner.admit(
                    brief=task,
                    session_key=session_key,
                    channel=channel,
                    chat_id=chat_id,
                    repo_path=repo,
                    base_ref=base,
                    backend_name=backend,
                    acceptance_cmd=acceptance,
                )
            except Exception as e:
                return self.payload("error", error=str(e))

            if wait:
                # Run inline
                try:
                    result_text = await runner.execute_task(
                        task_obj, backend_obj, repo_cfg, files=files, wait=True
                    )
                    return ToolResult(result_text)
                except Exception as e:
                    return self.payload("error", error=str(e))

            # Run in background
            spawn_background(
                runner.execute_task(task_obj, backend_obj, repo_cfg, files=files, wait=False),
                name=f"coding-{task_obj.id}",
            )
            return self.payload(
                "started",
                id=task_obj.id,
                backend=task_obj.backend,
                branch=task_obj.branch,
                worktree=task_obj.worktree,
                note=(
                    "Task started in background. END your turn now; you will be automatically "
                    "notified when it completes. Do not poll in a loop."
                ),
            )

        if act == "status":
            if not id:
                return self.payload("error", error="Task 'id' is required for 'status'.")
            t = runner.registry.get(id)
            if not t:
                return self.payload("error", error=f"Task '{id}' not found.")
            return self.payload(
                t.status,
                id=t.id,
                backend=t.backend,
                branch=t.branch,
                brief=t.brief,
                commits=t.commits,
                stats=t.stats,
                error=t.error,
            )

        if act == "steer":
            if not id or not message:
                return self.payload("error", error="Task 'id' and 'message' are required for 'steer'.")
            try:
                await runner.steer(id, message)
                return self.payload("ok", id=id, message="Steering message sent.")
            except Exception as e:
                return self.payload("error", error=str(e))

        if act == "abort":
            if not id:
                return self.payload("error", error="Task 'id' is required for 'abort'.")
            try:
                await runner.abort(id)
                return self.payload("ok", id=id, message="Task aborted.")
            except Exception as e:
                return self.payload("error", error=str(e))

        if act == "result":
            if not id:
                return self.payload("error", error="Task 'id' is required for 'result'.")
            t = runner.registry.get(id)
            if not t:
                return self.payload("error", error=f"Task '{id}' not found.")
            return self.payload(
                t.status,
                id=t.id,
                summary=t.summary,
                diffstat=t.diffstat,
                commits=t.commits,
                acceptance=t.acceptance_output,
                error=t.error,
            )

        if act == "diff":
            if not id:
                return self.payload("error", error="Task 'id' is required for 'diff'.")
            t = runner.registry.get(id)
            if not t:
                return self.payload("error", error=f"Task '{id}' not found.")
            worktree = Path(t.worktree) if t.worktree else None
            if worktree is None or not worktree.exists():
                return self.payload("error", error=f"Worktree for task '{id}' is no longer available.")
            diff_text = await runner.workspace_mgr.get_full_diff(worktree, t.base)
            if not diff_text.strip():
                return self.payload("ok", id=t.id, diff="", note="No diff against the base ref.")
            total = len(diff_text)
            truncated = total > DIFF_MAX_CHARS
            if truncated:
                diff_text = diff_text[:DIFF_MAX_CHARS]
            return self.payload(
                "ok",
                id=t.id,
                branch=t.branch,
                diffstat=t.diffstat,
                truncated=truncated,
                total_chars=total,
                diff=diff_text,
                note=(
                    f"Diff truncated to {DIFF_MAX_CHARS} of {total} characters; "
                    "read specific files in the worktree for the rest."
                    if truncated
                    else None
                ),
            )

        return self.payload("error", error=f"Unknown action: {action!r}")
