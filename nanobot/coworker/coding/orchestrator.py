"""Phase-based orchestrator driving Pi through the v2 RPC client (PiClient)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

import nanobot.coworker.coding.direct as direct_mod
from nanobot.coworker import metrics_store
from nanobot.coworker.coding import guard
from nanobot.coworker.coding.contract import CodingContract
from nanobot.coworker.coding.pi import EXTENSION_PATH
from nanobot.coworker.coding.pi import entries as pi_entries
from nanobot.coworker.coding.pi.client import PiClient
from nanobot.coworker.coding.pi.questions import (
    PendingQuestion,
    QuestionRouter,
    register_router,
    unregister_router,
)
from nanobot.coworker.coding.review import run_review
from nanobot.coworker.coding.runtime import ModelSpec, RunOutcome, SessionSpec
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
    if task.report and task.report.get("summary"):
        lines.append(f"**Report**: {task.report.get('summary')}")
    if task.review:
        verdict = task.review.get("verdict", "unknown")
        rev_summary = task.review.get("summary", "")
        lines.append(f"**Review**: `{verdict}` ({rev_summary})")
        blocking = [f for f in _dict_items(task.review.get("findings")) if f.get("severity") in ("blocking", "major")]
        if blocking:
            lines.append("**Open findings**:")
            lines.extend(
                f"- [{f.get('severity')}] {f.get('file', '')}:{f.get('line', '')} {f.get('issue', '')}"
                for f in blocking[:10]
            )
    if task.blocked_calls:
        lines.append(f"**Blocked calls**: {task.blocked_calls}")
    if task.settle_continuations:
        lines.append(f"**Settle continuations**: {task.settle_continuations}")
    if task.export_html_path:
        lines.append(f"**Transcript**: `{task.export_html_path}`")
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


def format_plan_message(task: CodingTask) -> str:
    plan = task.plan or {}
    summary = plan.get("summary") or "Plan ready."
    steps = _list_items(plan.get("plan_steps"))
    lines = [
        f"[auto-coding-plan] Plan submitted for task `{task.id}`.",
        f"**Summary**: {summary}",
    ]
    if steps:
        lines.append("**Steps**:")
        lines.extend(f"- {step}" for step in steps[:20])
    lines.extend([
        "",
        f"Call `coding_agent(action='approve', id='{task.id}')` to implement, "
        f"or `coding_agent(action='revise_plan', id='{task.id}', feedback='...')` to request changes. "
        f"You can also `/code approve {task.id}` or `/code revise {task.id} <feedback>`.",
    ])
    return "\n".join(lines)


class CodingOrchestrator:
    """State-machine orchestrator driving: Prepare -> Plan -> AwaitApproval -> Implement -> Review -> Fix -> Deliver."""

    def __init__(
        self,
        config: CoworkerConfig,
        workspace_root: Path,
        active_clients: dict[str, PiClient],
    ) -> None:
        self.config = config
        self.workspace_root = workspace_root
        self.workspace_mgr = WorkspaceManager(config.coding, workspace_root)
        self.registry = shared_registry(workspace_root)
        self._active_backends = active_clients

    async def _transition_phase(self, task: CodingTask, next_phase: Any) -> None:
        task.phase = next_phase
        task.updated_at = time.time()
        self.registry.save(task)

    def _model_for_phase(self, phase: str) -> ModelSpec | None:
        phases = getattr(self.config.coding.pi, "phases", None)
        phase_cfg = getattr(phases, phase, None) if phases is not None else None
        if phase_cfg is None or (not phase_cfg.model and not phase_cfg.thinking):
            return None
        provider: str | None = None
        model: str | None = phase_cfg.model
        if model and "/" in model:
            provider, model = model.split("/", 1)
        return ModelSpec(provider=provider, model=model, thinking=phase_cfg.thinking)

    async def _apply_phase_model(self, client: PiClient, phase: str) -> None:
        spec = self._model_for_phase(phase)
        if spec is None:
            return
        try:
            if spec.provider and spec.model:
                await client.set_model(provider=spec.provider, model=spec.model)
            if spec.thinking:
                await client.set_thinking_level(spec.thinking)
        except Exception as exc:  # pragma: no cover - defensive; Pi may not expose set_model
            logger.warning(f"Could not apply {phase} phase model live ({exc}); keeping current model")

    def _make_question_callback(self, task: CodingTask) -> Any:
        def _on_question(pending: PendingQuestion) -> Any:
            task.questions.append({
                "question_id": pending.question_id,
                "question": pending.question,
                "blocking_reason": pending.blocking_reason,
                "options": list(pending.options),
                "status": "pending",
            })
            task.updated_at = time.time()
            self.registry.save(task)
            try:
                return inject_turn(
                    session_key=task.session_key,
                    channel=task.channel,
                    chat_id=task.chat_id,
                    kind="coding_question",
                    content=f"Coding task `{task.id}` asks: {pending.question}",
                    extra={
                        "task_id": task.id,
                        "question_id": pending.question_id,
                        "question": pending.question,
                        "options": pending.options,
                    },
                )
            except Exception as exc:  # pragma: no cover
                logger.warning(f"Task {task.id}: could not notify coordinator of question: {exc}")
                return None

        return _on_question

    def _record_phase(self, task: CodingTask, phase: str, outcome: RunOutcome, seconds: float) -> None:
        task.phase_stats[phase] = {
            "tokens": outcome.stats.total_tokens,
            "cost": outcome.stats.cost,
            "seconds": round(seconds, 2),
        }
        if outcome.summary:
            task.summary = outcome.summary

    async def _collect_entries(self, client: PiClient, task: CodingTask, *, kind: str) -> None:
        """Read new bridge entries and store the report for the given phase kind."""
        try:
            entries = await client.get_entries(since=task.entry_cursor)
        except Exception as exc:
            logger.warning(f"Task {task.id}: get_entries failed: {exc}")
            return
        task.entry_cursor = client.last_leaf_id or task.entry_cursor
        if client.session_file:
            task.pi_session_file = client.session_file
        task.blocked_calls += pi_entries.count_blocks(entries)
        gate = pi_entries.extract_gate(entries)
        if gate:
            used = gate.get("continuations_used", gate.get("continuations"))
            if isinstance(used, int):
                task.settle_continuations += used
        report = pi_entries.extract_report(entries, kind=kind)
        if report is None:
            return
        if kind == "plan":
            task.plan = report
        elif kind == "review":
            task.review = report
        else:
            task.report = report

    def _is_stopped(self, task: CodingTask) -> bool:
        return task.status in ("timed_out", "error", "aborted")

    def _usable_session_file(self, task: CodingTask, task_dir: Path) -> Path | None:
        """Reuse a Pi session only when the file still exists under this task's artifact dir."""
        if not task.pi_session_file:
            return None
        try:
            resolved = Path(task.pi_session_file).resolve()
            resolved.relative_to(task_dir.resolve())
        except (OSError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    def _should_auto_approve(self, task: CodingTask, *, wait: bool) -> bool:
        if wait or self.config.coding.plan_approval == "never":
            return True
        if self.config.coding.plan_approval == "always":
            return False
        steps = _list_items(task.plan.get("plan_steps")) if task.plan else []
        open_q = _list_items(task.plan.get("open_questions")) if task.plan else []
        if not steps or len(steps) > self.config.coding.plan_auto_max_steps or open_q:
            return False
        return True

    def _implement_prompt(self, task: CodingTask, extra: str | None = None) -> str:
        prompt = extra.strip() if extra and extra.strip() else "Implement the approved plan now."
        if task.plan:
            steps_str = "\n".join(f"- {s}" for s in _list_items(task.plan.get("plan_steps")))
            if steps_str:
                prompt += f"\n\nFollow the approved plan:\n{steps_str}"
        return (
            prompt
            + "\n\nWhen finished, call report_result(kind='implementation', status='done', "
            "summary='...', changes=[...], tests_run=[...])."
        )

    async def _park_for_approval(self, task: CodingTask, client: PiClient) -> str:
        if client.session_file:
            task.pi_session_file = client.session_file
        plan_summary = task.plan.get("summary", "") if task.plan else "Plan ready."
        try:
            await inject_turn(
                session_key=task.session_key,
                channel=task.channel,
                chat_id=task.chat_id,
                kind="coding_plan",
                content=f"Plan submitted for task {task.id}: {plan_summary}",
                extra={"task_id": task.id, "plan": task.plan or {}},
            )
        except Exception as exc:
            logger.warning(f"Task {task.id}: could not notify coordinator of plan: {exc}")
        task.status = "awaiting_approval"
        task.error = None
        task.finished_at = 0.0
        self.registry.save(task)
        self._active_backends.pop(task.id, None)
        return format_plan_message(task)

    async def _export_html(self, client: PiClient, task: CodingTask, task_dir: Path) -> None:
        try:
            exported = await client.export_html(task_dir / "session.html")
            if exported:
                task.export_html_path = exported
        except Exception as exc:
            logger.debug(f"Task {task.id}: export_html failed: {exc}")

    async def _review_and_fix(
        self,
        task: CodingTask,
        client: PiClient,
        task_dir: Path,
        *,
        is_direct: bool,
        before_manifest: direct_mod.Manifest | None,
        max_fix_rounds: int,
    ) -> None:
        """Run the independent review, looping into a fix round while blocking findings remain."""
        if not self.config.coding.review or self._is_stopped(task):
            return
        for current_round in range(max_fix_rounds + 1):
            await self._transition_phase(task, "review")
            direct_patch_file = None
            if is_direct:
                patch_dir = task_dir / "review"
                patch_dir.mkdir(parents=True, exist_ok=True)
                patch_path = patch_dir / "changes.patch"
                diff_manifest = (
                    direct_mod.diff_manifest(before_manifest, Path(task.workdir))
                    if before_manifest
                    else None
                )
                diff_dump = diff_manifest.to_dict() if diff_manifest is not None else {}
                patch_path.write_text(json.dumps(diff_dump, indent=2), encoding="utf-8")
                direct_patch_file = str(patch_path)

            review_started = time.time()
            try:
                review_res = await asyncio.wait_for(
                    run_review(
                        self.config,
                        task,
                        direct_patch_path=direct_patch_file,
                        artifacts_dir=task_dir / "review",
                    ),
                    timeout=min(self.config.coding.timeout_minutes * 60, 300.0),
                )
            except Exception as exc:
                logger.warning(f"Task {task.id}: review timed out or failed: {exc}")
                review_res = {"verdict": "error", "summary": f"review timed out or failed ({exc})"}

            task.review = review_res
            task.phase_stats["review"] = {
                "tokens": 0,
                "cost": 0.0,
                "seconds": round(time.time() - review_started, 2),
            }
            self.registry.save(task)
            verdict = review_res.get("verdict", "pass")
            findings = _dict_items(review_res.get("findings"))
            blocking_findings = [
                f for f in findings if f.get("severity") in ("blocking", "major")
            ]

            if verdict == "pass" or not blocking_findings or current_round >= max_fix_rounds:
                break

            # FIX PHASE
            await self._transition_phase(task, "fix")
            task.fix_round += 1
            fix_prompt = "Review requested changes:\n" + "\n".join(
                f"- [{f.get('severity')}] {f.get('file', '')}:{f.get('line', '')} "
                f"{f.get('issue', '')} -> Fix: {f.get('fix', '')}"
                for f in blocking_findings
            )
            fix_prompt += (
                "\n\nAddress the findings and call "
                "report_result(kind='implementation', status='done', ...)."
            )
            started = time.time()
            outcome = await client.follow_up(fix_prompt)
            self._record_phase(task, "fix", outcome, time.time() - started)
            await self._collect_entries(client, task, kind="implementation")
            self._apply_outcome_status(task, outcome)
            if self._is_stopped(task):
                break

    def _apply_outcome_status(self, task: CodingTask, outcome: RunOutcome) -> bool:
        """Map a non-success run outcome to task status. Returns True when the task must stop."""
        if outcome.status in ("succeeded", "handled"):
            return False
        if outcome.status == "timed_out":
            task.status = "timed_out"
            task.error = outcome.error or "Timed out"
        elif outcome.status == "aborted":
            task.status = "aborted"
            task.error = outcome.error or "Aborted"
        else:
            task.status = "error"
            task.error = outcome.error or "Pi run failed"
            task.raw_error_line = outcome.error or task.raw_error_line
        return True

    async def execute_task(
        self,
        task: CodingTask,
        client: PiClient,
        repo: RepoConfig,
        *,
        files: list[str] | None = None,
        wait: bool = False,
    ) -> str:
        """Run the persistent phase state machine."""
        is_direct = task.mode == "direct"
        before_manifest: direct_mod.Manifest | None = None

        # 4.5 wait mode enforcement
        if wait and self.config.coding.wait_max_minutes > self.config.coding.timeout_minutes:
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
        task.pi_session_file = None  # real session file is captured from Pi after the first settle
        self.registry.save(task)

        # Build the structured contract consumed by the extension's policy and sections.
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
        plan_mode = contract_obj.mode == "plan_first"
        contract_obj.write_task_contract_json(
            contract_path,
            task_id=task.id,
            worktree_root=run_dir,
            bridge_mode="plan" if plan_mode else "implement",
            ask_enabled=not wait,
            max_continuations=self.config.coding.settle_max_continuations,
        )

        # Every ask_coordinator dialog is routed to the main agent (never straight to the user).
        router = QuestionRouter(
            default_timeout_s=self.config.coding.ask_timeout_minutes * 60,
            user_timeout_s=self.config.coding.ask_user_timeout_minutes * 60,
            on_question_created=self._make_question_callback(task),
        )
        client.question_router = router
        register_router(task.id, router)

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

        self._active_backends[task.id] = client

        try:
            try:
                await client.start(
                    cwd=run_dir,
                    session=SessionSpec(task_id=task.id, session_dir=session_dir),
                    extension=EXTENSION_PATH if self.config.coding.pi.extensions else None,
                    contract_file=contract_path,
                    model=self._model_for_phase("plan"),
                )
            except Exception as exc:
                logger.exception(f"Task {task.id}: failed to start Pi: {exc}")
                task.status = "error"
                task.error = f"Failed to start Pi: {exc}"
                return await self._deliver(task, wait, before_manifest, watch)

            # 2. PLAN PHASE (if plan_first)
            if plan_mode and not self._is_stopped(task):
                await self._transition_phase(task, "plan")
                plan_prompt = (
                    f"Examine the repository and the task objective: '{contract_obj.objective}'. "
                    "Formulate a clear plan with numbered steps that covers every acceptance criterion, "
                    "then call report_result(kind='plan', plan_steps=[...], summary='...'). "
                    "Do not modify source files."
                )
                started = time.time()
                outcome = await client.run_prompt(plan_prompt)
                self._record_phase(task, "plan", outcome, time.time() - started)
                await self._collect_entries(client, task, kind="plan")
                if self._apply_outcome_status(task, outcome):
                    return await self._deliver(task, wait, before_manifest, watch)

                # Check that the plan phase left the (direct) project untouched.
                if is_direct and before_manifest:
                    diffs = direct_mod.diff_manifest(before_manifest, Path(task.workdir))
                    if diffs.added or diffs.modified or diffs.deleted:
                        logger.warning(f"Task {task.id}: direct plan phase modified files; restoring")
                        direct_mod.restore(
                            before_manifest,
                            Path(task.snapshot),
                            Path(task.workdir),
                            diffs,
                            since=0.0,
                            force=True,
                        )

                # 3. AWAIT_APPROVAL PHASE
                await self._transition_phase(task, "await_approval")
                if not self._should_auto_approve(task, wait=wait):
                    return await self._park_for_approval(task, client)

            # 4. IMPLEMENT PHASE
            if not self._is_stopped(task):
                await self._transition_phase(task, "implement")
                contract_obj.write_task_contract_json(
                    contract_path,
                    task_id=task.id,
                    worktree_root=run_dir,
                    bridge_mode="implement",
                    ask_enabled=not wait,
                    max_continuations=self.config.coding.settle_max_continuations,
                    plan=task.plan.get("summary", "") if task.plan else None,
                )
                await self._apply_phase_model(client, "implement")
                try:
                    await client.run_prompt("/nanobot-mode implement")
                except Exception as exc:
                    logger.debug(f"Task {task.id}: /nanobot-mode implement failed: {exc}")

                implement_prompt = self._implement_prompt(task)

                started = time.time()
                outcome = await client.run_prompt(implement_prompt)
                self._record_phase(task, "implement", outcome, time.time() - started)
                await self._collect_entries(client, task, kind="implementation")
                self._apply_outcome_status(task, outcome)

            # 5. REVIEW & 6. FIX PHASES
            max_fix_rounds = min(self.config.coding.fix_rounds, 1) if wait else self.config.coding.fix_rounds
            await self._review_and_fix(
                task,
                client,
                task_dir,
                is_direct=is_direct,
                before_manifest=before_manifest,
                max_fix_rounds=max_fix_rounds,
            )
            if not self._is_stopped(task):
                await self._export_html(client, task, task_dir)
        finally:
            try:
                await client.close()
            except Exception:
                logger.debug(f"Task {task.id}: client close failed", exc_info=True)
            unregister_router(task.id)

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
        """Commit remaining changes, evaluate success, format results, and clean up the client."""
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

        # Aggregate per-phase stats for the delivery message.
        if task.phase_stats:
            total_tokens = sum(int(s.get("tokens", 0)) for s in task.phase_stats.values())
            total_cost = sum(float(s.get("cost", 0.0)) for s in task.phase_stats.values())
            task.stats = {"total_tokens": total_tokens, "cost": total_cost}

        # Final verdict status
        if not self._is_stopped(task):
            if task.review and task.review.get("verdict") == "changes_requested":
                task.status = "failed_acceptance"
            else:
                task.status = "succeeded"

        task.finished_at = time.time()
        self.registry.save(task)

        metrics_store.record_coding_run(
            task_id=task.id,
            backend=task.backend,
            mode=task.mode,
            status=task.status,
            fix_rounds=task.fix_round,
            settle_continuations=task.settle_continuations,
            blocked_calls=task.blocked_calls,
            questions=len(task.questions),
            total_tokens=int((task.stats or {}).get("total_tokens", 0)),
            cost=float((task.stats or {}).get("cost", 0.0) or 0.0),
            duration_ms=int(max(0.0, task.finished_at - task.created_at) * 1000),
            phase_stats=task.phase_stats,
        )

        # Cleanup client if still registered (the approval dead-end already popped it).
        client = self._active_backends.pop(task.id, None)
        if client is not None:
            try:
                await client.close()
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

    async def resume_task(
        self,
        task: CodingTask,
        client: PiClient,
        *,
        message: str | None = None,
        wait: bool = False,
    ) -> str:
        """Re-attach to an interrupted task, reconcile its session, and drive it to delivery."""
        if task.phase == "await_approval" or task.status == "awaiting_approval":
            task.status = "awaiting_approval"
            self.registry.save(task)
            return (
                f"[auto-coding-plan] Task `{task.id}` is still awaiting plan approval. "
                f"Approve with `coding_agent(action='approve', id='{task.id}')` or "
                f"`/code approve {task.id}` (or revise the plan) before resuming."
            )
        resume_message = message or (
            "The previous session was interrupted. Check `git status` and continue from where you stopped."
        )
        return await self._continue_from_session(
            task, client, wait=wait, phase="implement", follow_up=resume_message
        )

    async def continue_approved_plan(
        self,
        task: CodingTask,
        client: PiClient,
        *,
        notes: str | None = None,
        wait: bool = False,
    ) -> str:
        """Resume a parked plan-approval task into the implement phase."""
        return await self._continue_from_session(
            task,
            client,
            wait=wait,
            phase="implement",
            follow_up=self._implement_prompt(task, notes),
        )

    async def revise_plan(
        self,
        task: CodingTask,
        client: PiClient,
        *,
        feedback: str,
        wait: bool = False,
    ) -> str:
        """Re-run the plan phase with coordinator feedback, then auto-approve or park again."""
        plan_prompt = (
            f"Revise the plan using this feedback: {feedback}\n"
            "Formulate an updated plan with numbered steps that covers every acceptance criterion, "
            "then call report_result(kind='plan', plan_steps=[...], summary='...'). "
            "Do not modify source files."
        )
        return await self._continue_from_session(
            task, client, wait=wait, phase="plan", follow_up=plan_prompt
        )

    async def _continue_from_session(
        self,
        task: CodingTask,
        client: PiClient,
        *,
        wait: bool,
        phase: str,
        follow_up: str,
    ) -> str:
        """Restart Pi from the saved session (or a fresh one) and continue the state machine."""
        is_direct = task.mode == "direct"
        before_manifest: direct_mod.Manifest | None = None
        if is_direct and task.snapshot:
            before_manifest = await asyncio.to_thread(direct_mod.load_manifest, Path(task.snapshot))

        run_dir = task.run_dir
        task_dir = self.registry.task_dir(task.id)
        session_dir = task_dir / "session"
        session_dir.mkdir(parents=True, exist_ok=True)
        contract_path = task_dir / "task-contract.json"
        contract_obj = (
            CodingContract.from_dict(task.contract)
            if task.contract
            else CodingContract(
                objective=task.brief,
                context=task.brief,
                acceptance_criteria=[f"Verify {task.brief}"],
                acceptance_cmd=task.acceptance,
            )
        )
        if not contract_path.exists():
            contract_obj.write_task_contract_json(
                contract_path,
                task_id=task.id,
                worktree_root=run_dir,
                bridge_mode="plan" if phase == "plan" else "implement",
                ask_enabled=not wait,
                max_continuations=self.config.coding.settle_max_continuations,
                plan=task.plan.get("summary", "") if task.plan else None,
            )

        router = QuestionRouter(
            default_timeout_s=self.config.coding.ask_timeout_minutes * 60,
            user_timeout_s=self.config.coding.ask_user_timeout_minutes * 60,
            on_question_created=self._make_question_callback(task),
        )
        client.question_router = router
        register_router(task.id, router)
        self._active_backends[task.id] = client
        task.status = "running"
        self.registry.save(task)

        try:
            session_file = self._usable_session_file(task, task_dir)
            try:
                await client.start(
                    cwd=run_dir,
                    session=SessionSpec(
                        task_id=task.id,
                        session_file=session_file,
                        session_dir=None if session_file else session_dir,
                    ),
                    extension=EXTENSION_PATH if self.config.coding.pi.extensions else None,
                    contract_file=contract_path if contract_path.exists() else None,
                    model=self._model_for_phase("plan" if phase == "plan" else "implement"),
                )
            except Exception as exc:
                logger.exception(f"Task {task.id}: failed to resume Pi: {exc}")
                task.status = "error"
                task.error = f"Failed to resume Pi: {exc}"
                return await self._deliver(task, wait, before_manifest, None)

            try:
                entries = await client.get_entries(since=task.entry_cursor)
                task.entry_cursor = client.last_leaf_id or task.entry_cursor
                task.blocked_calls += pi_entries.count_blocks(entries)
            except Exception as exc:
                logger.warning(f"Task {task.id}: resume get_entries failed: {exc}")

            prompt_fn = client.follow_up if session_file else client.run_prompt

            if phase == "plan":
                await self._transition_phase(task, "plan")
                started = time.time()
                outcome = await prompt_fn(follow_up)
                self._record_phase(task, "plan", outcome, time.time() - started)
                await self._collect_entries(client, task, kind="plan")
                if self._apply_outcome_status(task, outcome):
                    return await self._deliver(task, wait, before_manifest, None)
                if is_direct and before_manifest:
                    diffs = direct_mod.diff_manifest(before_manifest, Path(task.workdir))
                    if diffs.added or diffs.modified or diffs.deleted:
                        logger.warning(f"Task {task.id}: direct plan phase modified files; restoring")
                        direct_mod.restore(
                            before_manifest,
                            Path(task.snapshot),
                            Path(task.workdir),
                            diffs,
                            since=0.0,
                            force=True,
                        )
                await self._transition_phase(task, "await_approval")
                if not self._should_auto_approve(task, wait=wait):
                    return await self._park_for_approval(task, client)
                follow_up = self._implement_prompt(task)

            if not self._is_stopped(task):
                await self._transition_phase(task, "implement")
                contract_obj.write_task_contract_json(
                    contract_path,
                    task_id=task.id,
                    worktree_root=run_dir,
                    bridge_mode="implement",
                    ask_enabled=not wait,
                    max_continuations=self.config.coding.settle_max_continuations,
                    plan=task.plan.get("summary", "") if task.plan else None,
                )
                await self._apply_phase_model(client, "implement")
                try:
                    await client.run_prompt("/nanobot-mode implement")
                except Exception as exc:
                    logger.debug(f"Task {task.id}: /nanobot-mode implement failed: {exc}")
                started = time.time()
                outcome = await prompt_fn(follow_up)
                self._record_phase(task, "implement", outcome, time.time() - started)
                await self._collect_entries(client, task, kind="implementation")
                self._apply_outcome_status(task, outcome)

            await self._review_and_fix(
                task,
                client,
                task_dir,
                is_direct=is_direct,
                before_manifest=before_manifest,
                max_fix_rounds=self.config.coding.fix_rounds,
            )
            if not self._is_stopped(task):
                await self._export_html(client, task, task_dir)
        finally:
            try:
                await client.close()
            except Exception:
                logger.debug(f"Task {task.id}: resume client close failed", exc_info=True)
            unregister_router(task.id)

        await self._transition_phase(task, "deliver")
        return await self._deliver(task, wait, before_manifest, None)
