"""Phase-based orchestrator replacing runner.execute_task with persistent state machine."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

import nanobot.coworker.coding.direct as direct_mod
from nanobot.coworker.coding import guard
from nanobot.coworker.coding.backends.base import (
    BackendEventDone,
    BackendEventTool,
    CodingBackend,
)
from nanobot.coworker.coding.backends.pi import PiBackend
from nanobot.coworker.coding.brief import (
    render_brief,
    render_rules,
)
from nanobot.coworker.coding.contract import CodingContract
from nanobot.coworker.coding.review import run_review
from nanobot.coworker.coding.tasks import (
    CodingTask,
    shared_registry,
)
from nanobot.coworker.coding.workspace import WorkspaceManager
from nanobot.coworker.runtime import inject_turn

if TYPE_CHECKING:
    from nanobot.coworker.config import CoworkerConfig, RepoConfig


_DELIVERY_FILE_LIMIT = 20


def _dict_items(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in cast(list[object], value):
        if isinstance(item, dict):
            out.append(cast(dict[str, Any], item))
    return out


def _list_items(value: object) -> list[Any]:
    if not isinstance(value, list):
        return []
    return list(cast(list[object], value))



def format_delivery_message(task: CodingTask) -> str:
    acc_text = "None configured"
    if task.acceptance:
        status_str = "Passed" if task.status == "succeeded" else "Failed"
        acc_text = f"`{task.acceptance}`: {status_str}"

    stats = task.stats or {}
    tokens_info = f"{stats.get('total_tokens', 0)} tokens"
    if stats.get("cost"):
        tokens_info += f" (${stats.get('cost', 0.0):.4f})"

    is_direct = task.mode == "direct"
    lines = [
        f"[auto-coding-result] Task `{task.id}` ({task.backend}) finished with status: `{task.status}`",
        f"**Phase**: {task.phase}",
        f"**Goal**: {task.brief}",
        f"**Harness Summary**: {task.summary or 'None'}",
        (
            f"**Changes**: {task.diffstat or 'none'} (edited in place in `{task.workdir}`, no branch)"
            if is_direct
            else f"**Commits**: {len(task.commits)} commit(s) on `{task.branch}`"
        ),
        f"**Tokens**: {tokens_info}",
        f"**Acceptance**: {acc_text}",
    ]
    if task.review:
        verdict = task.review.get("verdict", "unknown")
        rev_summary = task.review.get("summary", "")
        lines.append(f"**Review**: `{verdict}` ({rev_summary})")
    if task.error:
        lines.append(f"**Error**: {task.error}")
    if task.outside_writes:
        lines.extend([
            "⚠️ **Files changed outside the project while the task ran** (review them, "
            "they are not covered by merge/discard):",
            "```",
            *task.outside_writes,
            "```",
        ])
    if is_direct:
        files = [
            f"{mark} {path}"
            for mark, key in (("+", "added"), ("~", "modified"), ("-", "deleted"))
            for path in task.changes.get(key, [])
        ]
        if files:
            shown = files[:_DELIVERY_FILE_LIMIT]
            if len(files) > len(shown):
                shown.append(f"… and {len(files) - len(shown)} more")
            lines.extend(["**Files**:", "```", *shown, "```"])
        lines.extend([
            "",
            "The changes are already applied. Review them, then tell the user they can keep them "
            f"or run `/code discard {task.id}` to undo them.",
        ])
    else:
        if task.diffstat:
            lines.extend(["**Diffstat**:", "```", task.diffstat, "```"])
        lines.extend([
            "",
            f"Review the results above, then tell the user to `/code merge {task.id}` "
            f"or `/code discard {task.id}`.",
        ])
    return "\n".join(lines)


class CodingOrchestrator:
    """State-machine orchestrator driving: Prepare -> Plan -> AwaitApproval -> Implement -> Review -> Fix -> Deliver."""

    def __init__(
        self,
        config: CoworkerConfig,
        workspace_root: Path,
        active_backends: dict[str, CodingBackend],
    ) -> None:
        self.config = config
        self.workspace_root = workspace_root
        self.workspace_mgr = WorkspaceManager(config.coding, workspace_root)
        self.registry = shared_registry(workspace_root)
        self._active_backends = active_backends

    async def _transition_phase(self, task: CodingTask, next_phase: Any) -> None:
        task.phase = next_phase
        task.updated_at = time.time()
        self.registry.save(task)

    async def execute_task(
        self,
        task: CodingTask,
        backend: CodingBackend,
        repo: RepoConfig,
        *,
        files: list[str] | None = None,
        wait: bool = False,
    ) -> str:
        """Run the persistent phase state machine."""
        is_direct = task.mode == "direct"
        before_manifest: direct_mod.Manifest | None = None

        # 4.5 wait mode enforcement
        if wait:
            if self.config.coding.wait_max_minutes > self.config.coding.timeout_minutes:
                task.status = "error"
                task.error = (
                    f"wait_max_minutes ({self.config.coding.wait_max_minutes}) exceeds "
                    f"timeout_minutes ({self.config.coding.timeout_minutes})"
                )
                task.finished_at = time.time()
                self.registry.save(task)
                return format_delivery_message(task)

        # 1. PREPARE PHASE
        await self._transition_phase(task, "prepare")
        try:
            if is_direct:
                snapshot_dir = self.workspace_mgr.worktree_base / task.id / "snapshot"
                before_manifest = await asyncio.to_thread(
                    direct_mod.take_snapshot,
                    Path(task.workdir),
                    snapshot_dir,
                    max_mb=self.config.coding.snapshot_max_mb,
                )
                task.snapshot = str(snapshot_dir)
            else:
                worktree_dir, branch_name = await self.workspace_mgr.create_worktree(
                    repo=repo,
                    task_id=task.id,
                    base_ref=task.base,
                )
                task.worktree = str(worktree_dir)
                task.branch = branch_name
                task.subdir = (await self.workspace_mgr.project_kind(repo)).rel
        except Exception as exc:
            logger.exception(f"Task {task.id} prepare failed: {exc}")
            task.status = "error"
            task.error = f"Setup failed: {exc}"
            task.finished_at = time.time()
            self.registry.save(task)
            return await self._deliver(task, wait)

        run_dir = task.run_dir
        task.status = "running"
        task_dir = self.registry.task_dir(task.id)
        session_dir = task_dir / "session"
        session_dir.mkdir(parents=True, exist_ok=True)
        task.pi_session_file = str(session_dir)
        self.registry.save(task)
        self._active_backends[task.id] = backend

        # Write initial task-contract.json
        contract_obj = CodingContract.from_dict(task.contract) if task.contract else CodingContract(
            objective=task.brief,
            context=task.brief,
            acceptance_criteria=[f"Verify {task.brief}"],
            acceptance_cmd=task.acceptance,
            files=files or [],
            mode="plan_first" if getattr(self.config.coding, "mode", "plan_first") == "plan_first" else "auto",
        )
        task.contract = contract_obj.to_dict()
        contract_path = task_dir / "task-contract.json"
        contract_obj.write_task_contract_json(
            contract_path,
            task_id=task.id,
            worktree_root=run_dir,
            bridge_mode="plan" if contract_obj.mode == "plan_first" else "implement",
            ask_enabled=not wait,
        )
        if isinstance(backend, PiBackend):
            backend.contract_file = contract_path

        watch: guard.WriteWatch | None = None
        try:
            watch = await asyncio.to_thread(
                guard.WriteWatch,
                run_dir,
                Path(task.workdir if is_direct else task.repo),
                direct=is_direct,
            )
        except Exception:
            logger.exception(f"Task {task.id}: could not snapshot paths for outside-write detection")

        wall_timeout_seconds = self.config.coding.timeout_minutes * 60
        idle_timeout_seconds = self.config.coding.idle_timeout_minutes * 60
        start_time = time.time()
        last_event_time = start_time
        watchdog_triggered = False

        async def _watchdog() -> None:
            nonlocal watchdog_triggered
            while True:
                await asyncio.sleep(0.5)
                now = time.time()
                if now - start_time > wall_timeout_seconds:
                    watchdog_triggered = True
                    logger.warning(f"Task {task.id} timed out (wall clock)")
                    task.status = "timed_out"
                    task.error = f"Wall clock timeout ({self.config.coding.timeout_minutes} minutes) exceeded"
                    await backend.abort()
                    break
                if now - last_event_time > idle_timeout_seconds:
                    watchdog_triggered = True
                    logger.warning(f"Task {task.id} timed out (idle)")
                    task.status = "timed_out"
                    task.error = f"Idle timeout ({self.config.coding.idle_timeout_minutes} minutes without events) exceeded"
                    await backend.abort()
                    break

        watchdog_task = asyncio.create_task(_watchdog())

        plan_mode = contract_obj.mode == "plan_first"

        try:
            # 2. PLAN PHASE (if plan_first)
            if plan_mode and not watchdog_triggered:
                await self._transition_phase(task, "plan")
                plan_prompt = (
                    f"Examine the repository and task objective: '{contract_obj.objective}'. "
                    "Formulate a clear plan with numbered steps and call report_result(kind='plan', plan_steps=[...], summary='...')."
                )
                rules = "## PLAN MODE RULES\nExplore read-only. Do not modify source code. Call report_result(kind='plan') when done."
                run = backend.start(
                    brief=plan_prompt,
                    cwd=run_dir,
                    rules=rules,
                    task_id=task.id,
                    session_dir=session_dir,
                )

                try:
                    async for event in run:
                        last_event_time = time.time()
                        if isinstance(event, BackendEventTool) and event.tool_name == "report_result":
                            if event.details:
                                task.plan = event.details
                        elif isinstance(event, BackendEventDone):
                            if event.resume_ref:
                                task.resume_ref = event.resume_ref
                            break
                        if watchdog_triggered:
                            break
                except Exception as exc:
                    logger.warning(f"Task {task.id} plan phase warning: {exc}")

                # Check clean after plan
                if is_direct and before_manifest:
                    diffs = direct_mod.diff_manifest(before_manifest, Path(task.workdir))
                    if diffs.added or diffs.modified or diffs.deleted:
                        logger.warning(f"Task {task.id}: direct plan phase modified files; restoring")
                        direct_mod.restore(before_manifest, Path(task.snapshot), Path(task.workdir), diffs, since=0.0, force=True)

                # 3. AWAIT_APPROVAL PHASE
                await self._transition_phase(task, "await_approval")
                auto_approved = True
                if not wait and self.config.coding.plan_approval == "always":
                    auto_approved = False
                elif not wait and self.config.coding.plan_approval == "auto":
                    steps = _list_items(task.plan.get("plan_steps")) if task.plan else []
                    open_q = _list_items(task.plan.get("open_questions")) if task.plan else []
                    if len(steps) > self.config.coding.plan_auto_max_steps or open_q:
                        auto_approved = False

                if not auto_approved:
                    # Plan not approved by auto criteria -> await approval or reject
                    plan_summary = task.plan.get("summary", "") if task.plan else "Plan ready."
                    await inject_turn(
                        session_key=task.session_key,
                        channel=task.channel,
                        chat_id=task.chat_id,
                        kind="coding_plan",
                        content=f"Plan submitted for task {task.id}: {plan_summary}",
                        extra={"task_id": task.id, "plan": task.plan or {}},
                    )
                    if self.config.coding.plan_approval == "always" or (
                        self.config.coding.plan_approval == "auto" and not auto_approved
                    ):
                        task.status = "awaiting_approval"
                        task.error = f"Plan awaiting approval for task {task.id}"
                        task.finished_at = time.time()
                        self.registry.save(task)
                        active_b = self._active_backends.pop(task.id, None)
                        if active_b:
                            try:
                                await active_b.abort()
                            except Exception:
                                pass
                        return (
                            f"[auto-coding-plan] Plan submitted for task `{task.id}`. "
                            f"(Approval workflow is deferred in current runtime; re-run with `plan_approval='never'` to auto-implement.)"
                        )

            # 4. IMPLEMENT PHASE
            if not watchdog_triggered:
                await self._transition_phase(task, "implement")
                contract_obj.write_task_contract_json(
                    contract_path,
                    task_id=task.id,
                    worktree_root=run_dir,
                    bridge_mode="implement",
                    ask_enabled=not wait,
                    plan=task.plan.get("summary", "") if task.plan else None,
                )

                implement_rules = render_rules(task.acceptance)
                implement_prompt = render_brief(contract_obj.objective, files)
                if task.plan:
                    steps_str = "\n".join(f"- {s}" for s in task.plan.get("plan_steps", []))
                    implement_prompt += f"\n\nFollow the approved plan:\n{steps_str}"

                run = backend.follow_up(
                    run_ref=task.resume_ref or str(session_dir),
                    message=implement_prompt,
                    cwd=run_dir,
                    rules=implement_rules,
                    task_id=task.id,
                    session_dir=session_dir,
                )

                try:
                    async for event in run:
                        last_event_time = time.time()
                        if isinstance(event, BackendEventTool):
                            if event.tool_name == "report_result" and event.details:
                                task.report = event.details
                            elif event.tool_name == "nanobot_block":
                                task.blocked_calls += 1
                        elif isinstance(event, BackendEventDone):
                            if event.result and event.result.response:
                                task.summary = event.result.response
                            if event.resume_ref:
                                task.resume_ref = event.resume_ref
                            break
                        if watchdog_triggered:
                            break
                except Exception as exc:
                    logger.warning(f"Task {task.id} implement phase warning: {exc}")

            # 5. REVIEW & 6. FIX PHASES
            max_fix_rounds = min(self.config.coding.fix_rounds, 1) if wait else self.config.coding.fix_rounds
            if self.config.coding.review and not watchdog_triggered:
                for current_round in range(max_fix_rounds + 1):
                    await self._transition_phase(task, "review")
                    direct_patch_file = None
                    if is_direct:
                        patch_dir = task_dir / "review"
                        patch_dir.mkdir(parents=True, exist_ok=True)
                        patch_path = patch_dir / "changes.patch"
                        diff_manifest = direct_mod.diff_manifest(before_manifest, Path(task.workdir)) if before_manifest else None
                        diff_dump = diff_manifest.to_dict() if diff_manifest is not None else {}
                        patch_path.write_text(json.dumps(diff_dump, indent=2), encoding="utf-8")
                        direct_patch_file = str(patch_path)

                    try:
                        review_res = await asyncio.wait_for(
                            run_review(self.config, task, direct_patch_path=direct_patch_file),
                            timeout=min(self.config.coding.timeout_minutes * 60, 300.0),
                        )
                    except Exception as exc:
                        logger.warning(f"Task {task.id}: review timed out or failed: {exc}")
                        review_res = {"verdict": "error", "summary": f"review timed out or failed ({exc})"}

                    task.review = review_res
                    verdict = review_res.get("verdict", "pass")
                    findings = _dict_items(review_res.get("findings"))
                    blocking_findings = [
                        f for f in findings if f.get("severity") in ("blocking", "major")
                    ]

                    if verdict == "pass" or not blocking_findings or current_round >= max_fix_rounds:
                        break

                    # 6. FIX PHASE
                    await self._transition_phase(task, "fix")
                    task.fix_round += 1
                    fix_prompt = "Review requested changes:\n" + "\n".join(
                        f"- [{f.get('severity')}] {f.get('file', '')}:{f.get('line', '')} {f.get('issue', '')} -> Fix: {f.get('fix', '')}"
                        for f in blocking_findings
                    )
                    fix_run = backend.follow_up(
                        run_ref=task.resume_ref or str(session_dir),
                        message=fix_prompt,
                        cwd=run_dir,
                        rules=render_rules(task.acceptance),
                        task_id=task.id,
                        session_dir=session_dir,
                    )
                    async for event in fix_run:
                        last_event_time = time.time()
                        if isinstance(event, BackendEventTool) and event.tool_name == "report_result":
                            if event.details:
                                task.report = event.details
                        elif isinstance(event, BackendEventDone):
                            break
                        if watchdog_triggered:
                            break
        finally:
            watchdog_task.cancel()

        # 7. DELIVER PHASE
        await self._transition_phase(task, "deliver")
        return await self._deliver(task, wait, before_manifest, watch)

    async def _deliver(
        self,
        task: CodingTask,
        wait: bool,
        before_manifest: direct_mod.Manifest | None = None,
        watch: guard.WriteWatch | None = None,
    ) -> str:
        """Commit remaining changes, evaluate success, format results, and clean up backend."""
        is_direct = task.mode == "direct"

        if not is_direct and task.worktree:
            try:
                wt_path = Path(task.worktree)
                await self.workspace_mgr.commit_uncommitted_changes(wt_path, task.backend)
                task.diffstat = await self.workspace_mgr.get_diffstat(wt_path, task.base)
                task.commits = await self.workspace_mgr.get_commits(wt_path, task.base)
            except Exception as exc:
                logger.warning(f"Task {task.id}: deliver commit error: {exc}")
        elif is_direct and before_manifest:
            diff = direct_mod.diff_manifest(before_manifest, Path(task.workdir))
            task.changes = diff.to_dict()
            task.diffstat = diff.summary()

        if watch is not None:
            try:
                rep = await asyncio.to_thread(watch.check)
            except Exception:
                logger.exception(f"Task {task.id}: outside-write check failed")
            else:
                if rep:
                    task.outside_writes = rep.lines()
                    if rep.critical and self.config.coding.outside_writes == "fail":
                        task.status = "error"
                        note = "The harness modified sensitive files outside the project directory."
                        task.error = f"{task.error} {note}" if task.error else note

        # Final verdict status
        if task.status not in ("error", "timed_out", "aborted"):
            if task.review and task.review.get("verdict") == "changes_requested":
                task.status = "failed_acceptance"
            else:
                task.status = "succeeded"

        task.finished_at = time.time()
        self.registry.save(task)

        # Cleanup backend
        backend = self._active_backends.pop(task.id, None)
        if backend:
            try:
                await backend.abort()
            except Exception:
                pass

        message = format_delivery_message(task)
        if not wait:
            await inject_turn(
                session_key=task.session_key,
                channel=task.channel,
                chat_id=task.chat_id,
                content=message,
                kind="coding_result",
                extra={"task_id": task.id},
            )

        return message
