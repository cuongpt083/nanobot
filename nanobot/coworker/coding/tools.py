"""The coding_agent tool exposing external harness delegation to the agent."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker.coding.contract import CodingContract
from nanobot.coworker.coding.pi.questions import get_router
from nanobot.coworker.coding.project import DirectConfirmationError
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.tasks import CodingTask
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
            "enum": [
                "start",
                "approve",
                "revise_plan",
                "answer",
                "status",
                "steer",
                "abort",
                "result",
                "diff",
            ],
            "description": "Action to perform: start (create task with contract), approve (approve plan), "
            "revise_plan (request changes to plan), answer (reply to coordinator question), "
            "status, steer, abort, result, or diff.",
        },
        "objective": {
            "type": "string",
            "description": "Clear, self-contained coding objective and requirements (required for 'start').",
        },
        "context": {
            "type": "string",
            "description": "Comprehensive context (architecture, decisions, references, min 120 chars) for 'start'.",
        },
        "acceptance_criteria": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of verifiable acceptance criteria for 'start'.",
        },
        "constraints": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional list of constraints or boundaries for 'start'.",
        },
        "out_of_scope": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional list of items explicitly out of scope for 'start'.",
        },
        "mode": {
            "type": "string",
            "enum": ["plan_first", "auto"],
            "description": "Execution strategy ('plan_first' or 'auto'). Defaults to 'plan_first'.",
        },
        "task": {
            "type": "string",
            "description": "Legacy task parameter. Provide 'objective', 'context', and 'acceptance_criteria' instead.",
        },
        "repo": {
            "type": "string",
            "description": (
                "Optional. Defaults to the project directory the user chose for this chat; "
                "only that directory or a configured repository is accepted."
            ),
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
            "description": "Task ID (ct-...) for status, steer, abort, result, diff, approve, revise_plan, or answer.",
        },
        "question_id": {
            "type": "string",
            "description": "Question ID when answering an ask_coordinator inquiry (action='answer').",
        },
        "answer": {
            "type": "string",
            "description": "Coordinator's answer for question_id (action='answer').",
        },
        "escalated": {
            "type": "boolean",
            "description": "Set to true when escalating question to user (action='answer') to extend timeout.",
        },
        "feedback": {
            "type": "string",
            "description": "Feedback message when revising plan (action='revise_plan').",
        },
        "notes": {
            "type": "string",
            "description": "Optional approval notes (action='approve').",
        },
        "message": {
            "type": "string",
            "description": "Message to send for the 'steer' action (Pi only).",
        },
    },
    "required": ["action"],
})
class CodingAgentTool(CoworkerTool):
    """Delegate coding work to Pi runtime in a git worktree, or in place for a non-git project."""

    @property
    def name(self) -> str:
        return CODING_TOOL

    @property
    def description(self) -> str:
        return (
            "Delegate multi-file coding, refactoring, or bug fixes with a structured contract "
            "and an acceptance test loop to Pi coding runtime in an isolated git worktree, "
            "or edit the project in place (with an undo snapshot) when not a git repository."
        )

    def _get_runner(self) -> CodingRunner:
        svc = services()
        ws_root = svc.workspace if svc is not None else Path.cwd()
        cfg = load_coworker_config()
        return CodingRunner(cfg, ws_root)

    async def _direct_diff(self, runner: CodingRunner, t: CodingTask) -> ToolResult:
        """Diff of an in-place task: the changed files plus a text diff when a snapshot copy exists."""
        changes: dict[str, list[str]] = t.changes
        if not any(changes.get(k) for k in ("added", "modified", "deleted")):
            return self.payload("ok", id=t.id, mode="direct", diff="", note="No files were changed.")
        try:
            text = await runner.direct_diff_text(t, limit=DIFF_MAX_CHARS + 1)
        except RuntimeError as exc:
            return self.payload("error", error=str(exc))
        truncated = len(text) > DIFF_MAX_CHARS
        notes: list[str] = []
        if truncated:
            text = text[:DIFF_MAX_CHARS]
            notes.append(f"Diff truncated to {DIFF_MAX_CHARS} characters; read the files for the rest.")
        if not text:
            notes.append("No text diff available (no copy of the originals was kept, or binary files).")
        return self.payload(
            "ok",
            id=t.id,
            mode="direct",
            workdir=t.workdir,
            changes=changes,
            diffstat=t.diffstat,
            truncated=truncated,
            diff=text,
            note=" ".join(notes) or None,
        )

    async def execute(
        self,
        action: str,
        task: str | None = None,
        objective: str | None = None,
        context: str | None = None,
        acceptance_criteria: list[str] | None = None,
        constraints: list[str] | None = None,
        out_of_scope: list[str] | None = None,
        mode: str | None = None,
        repo: str | None = None,
        base: str | None = None,
        acceptance: str | None = None,
        files: list[str] | None = None,
        wait: bool = False,
        id: str | None = None,
        question_id: str | None = None,
        answer: str | None = None,
        escalated: bool = False,
        feedback: str | None = None,
        notes: str | None = None,
        message: str | None = None,
        **extra: Any,
    ) -> ToolResult:
        runner = self._get_runner()
        act = action.strip().lower()

        if act == "start":
            # Check if using legacy parameter or modern contract
            if objective is not None:
                contract = CodingContract(
                    objective=objective,
                    context=context or "",
                    acceptance_criteria=acceptance_criteria or [],
                    constraints=constraints or [],
                    out_of_scope=out_of_scope or [],
                    acceptance_cmd=acceptance,
                    files=files or [],
                    mode="auto" if mode == "auto" else "plan_first",
                )
                min_ctx = getattr(runner.config.coding, "min_context_chars", 120)
                validation_errors = contract.validate(min_context_chars=min_ctx)
                if validation_errors:
                    return self.payload(
                        "error",
                        error="Contract validation failed:\n" + "\n".join(f"- {e}" for e in validation_errors),
                    )
                brief_text = contract.objective
                contract_warnings = contract.quality_warnings()
            elif task is not None and task.strip():
                # If caller provided repo or extra flags or in tests expecting legacy execution
                # We provide warning or allow fallback when caller asks
                brief_text = task.strip()
                contract_warnings = []
            else:
                return self.payload(
                    "error",
                    error="Required parameters for action='start': 'objective', 'context', and 'acceptance_criteria'.",
                )

            req = self.request()
            session_key = (req.session_key if req and req.session_key else None) or "default"
            channel = (req.channel if req and req.channel else None) or "cli"
            chat_id = (req.chat_id if req and req.chat_id else None) or "user"

            try:
                task_obj, backend_obj, repo_cfg = await runner.admit_async(
                    brief=brief_text,
                    session_key=session_key,
                    channel=channel,
                    chat_id=chat_id,
                    repo_path=repo,
                    base_ref=base,
                    backend_name="pi",
                    acceptance_cmd=acceptance,
                )
            except DirectConfirmationError as e:
                return self.payload(
                    "needs_confirmation", error=str(e), path=str(e.path), mode="direct"
                )
            except Exception as e:
                return self.payload("error", error=str(e))

            if objective is not None:
                task_obj.contract = contract.to_dict()
                if contract.acceptance_cmd:
                    task_obj.acceptance = contract.acceptance_cmd
                runner.registry.save(task_obj)

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
                mode=task_obj.mode,
                warnings=contract_warnings or None,
                note=(
                    "Task started in background. END your turn now; you will be automatically "
                    "notified when it completes. Do not poll in a loop."
                ),
            )

        if act == "approve":
            if not id:
                return self.payload("error", error="Task 'id' is required for 'approve'.")
            try:
                t = runner.claim_approval(id)
            except RuntimeError as e:
                return self.payload("error", error=str(e))
            spawn_background(
                runner.approve(t, notes=notes),
                name=f"coding-approve-{t.id}",
            )
            return self.payload(
                "ok",
                id=id,
                state="approved",
                notes=notes,
                note="Implementing the approved plan in the background. END your turn now.",
            )

        if act == "revise_plan":
            if not id:
                return self.payload("error", error="Task 'id' is required for 'revise_plan'.")
            if not (feedback or "").strip():
                return self.payload("error", error="'feedback' is required for 'revise_plan'.")
            try:
                t = runner.claim_approval(id)
            except RuntimeError as e:
                return self.payload("error", error=str(e))
            spawn_background(
                runner.revise_plan(t, feedback=feedback.strip()),
                name=f"coding-revise-{t.id}",
            )
            return self.payload(
                "ok",
                id=id,
                state="revision_requested",
                feedback=feedback,
                note="Revising the plan in the background. END your turn now.",
            )

        if act == "answer":
            if not id:
                return self.payload("error", error="Task 'id' is required for 'answer'.")
            if not question_id:
                return self.payload("error", error="Question 'question_id' is required for 'answer'.")
            t = runner.registry.get(id)
            if not t:
                return self.payload("error", error=f"Task '{id}' not found.")

            router = get_router(id)
            if router is None:
                return self.payload("error", error=f"Task '{id}' has no active question channel.")

            # Escalation extends the deadline to the user-approval window.
            if escalated:
                if router.escalate_to_user(question_id):
                    return self.payload("ok", id=id, question_id=question_id, state="escalated_to_user")
                return self.payload("error", error=f"No pending question '{question_id}' to escalate.")

            if answer is None:
                return self.payload("error", error="Either 'answer' or 'escalated=True' is required for 'answer'.")

            if router.answer_question(question_id, answer):
                return self.payload("ok", id=id, question_id=question_id, state="answered", answer=answer)
            return self.payload("error", error=f"No pending question '{question_id}' to answer.")

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
                mode=t.mode,
                branch=t.branch,
                changes=t.changes or None,
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
                settle_continuations=t.settle_continuations,
                review=t.review,
                export_html_path=t.export_html_path,
                error=t.error,
            )

        if act == "diff":
            if not id:
                return self.payload("error", error="Task 'id' is required for 'diff'.")
            t = runner.registry.get(id)
            if not t:
                return self.payload("error", error=f"Task '{id}' not found.")
            if t.mode == "direct":
                return await self._direct_diff(runner, t)
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
