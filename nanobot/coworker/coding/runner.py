"""Backend-neutral driver managing the lifecycle of coding tasks."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.coworker.coding import direct as direct_mod
from nanobot.coworker.coding import guard
from nanobot.coworker.coding.backends.base import (
    BackendEventDone,
    BackendEventError,
    BackendEventProgress,
    BackendEventTool,
    BackendStats,
    CodingBackend,
    backend_for,
)
from nanobot.coworker.coding.brief import (
    render_acceptance_failure_prompt,
    render_brief,
    render_rules,
)
from nanobot.coworker.coding.orchestrator import CodingOrchestrator
from nanobot.coworker.coding.project import (
    DirectConfirmationError,
    ProjectError,
    direct_allowed,
    resolve_project,
    set_pending_direct,
)
from nanobot.coworker.coding.tasks import (
    CodingTask,
    generate_task_id,
    shared_registry,
)
from nanobot.coworker.coding.workspace import WorkspaceManager
from nanobot.coworker.runtime import get_session, inject_turn, post_to_chat

if TYPE_CHECKING:
    from nanobot.coworker.config import CoworkerConfig, RepoConfig


# Running backends by task id, shared by every runner instance so steer/abort issued from a later
# tool call or `/code` command reaches the process started by an earlier one.
_ACTIVE_BACKENDS: dict[str, CodingBackend] = {}

_DELIVERY_FILE_LIMIT = 20


def _lookup_session(session_key: str) -> Any | None:
    """Session of the task's chat; None when unavailable (falls back to ``coding.repos``)."""
    try:
        return get_session(session_key)
    except Exception:
        logger.debug("coding: session lookup failed for {}; using coding.repos", session_key)
        return None


class CodingRunner:
    """Orchestrates coding tasks across workspace isolation, harnesses, and verification."""

    def __init__(self, config: CoworkerConfig, workspace_root: Path) -> None:
        self.config = config
        self.workspace_root = workspace_root
        self.workspace_mgr = WorkspaceManager(config.coding, workspace_root)
        self.registry = shared_registry(workspace_root)
        self._active_backends = _ACTIVE_BACKENDS
        self.orchestrator = CodingOrchestrator(config, workspace_root, self._active_backends)

    def admit(
        self,
        *,
        brief: str,
        session_key: str,
        channel: str,
        chat_id: str,
        repo_path: str | None = None,
        base_ref: str | None = None,
        backend_name: str | None = None,
        acceptance_cmd: str | None = None,
    ) -> tuple[CodingTask, CodingBackend, RepoConfig]:
        """Validate prerequisites, allocate task id, and prepare worktree."""
        if not self.config.coding.enabled:
            raise RuntimeError("coding_agent is disabled in configuration (coding.enabled is False).")

        # Resolve the project: the directory the user picked for this chat, else coding.repos.
        project = resolve_project(_lookup_session(session_key), self.config.coding, repo_path)
        repo = project.repo_config

        # Resolve backend
        resolved_backend_name = (
            backend_name or repo.backend or self.config.coding.default_backend
        ).strip().lower()

        # Check binary availability
        cmd_prefix = (
            self.config.coding.pi.command
            if resolved_backend_name == "pi"
            else self.config.coding.agy.command
        )
        binary = cmd_prefix[0] if cmd_prefix else resolved_backend_name
        # With coding.sandbox='wsl' the harness runs inside the distro; the sandbox checks it there.
        if (
            self.config.coding.sandbox != "wsl"
            and not shutil.which(binary)
            and not Path(binary).exists()
        ):
            raise RuntimeError(
                f"Backend '{resolved_backend_name}' binary '{binary}' is not installed or not found on PATH. "
                f"Please install and log in to {resolved_backend_name} in a terminal first."
            )

        # Check concurrency limits
        total_active = self.registry.count_active()
        if total_active >= self.config.coding.max_concurrent_total:
            raise RuntimeError(
                f"Total concurrent coding tasks limit reached ({total_active}/{self.config.coding.max_concurrent_total})."
            )

        session_active = self.registry.count_active(session_key)
        if session_active >= self.config.coding.max_concurrent_per_session:
            raise RuntimeError(
                f"Per-session concurrent coding tasks limit reached ({session_active}/{self.config.coding.max_concurrent_per_session})."
            )

        task_id = generate_task_id()
        backend = backend_for(resolved_backend_name, self.config)

        task = CodingTask(
            id=task_id,
            backend=resolved_backend_name,
            session_key=session_key,
            channel=channel,
            chat_id=chat_id,
            repo=repo.path,
            base=base_ref or repo.base_ref,
            branch=f"coworker/code/{task_id}",
            worktree="",  # populated upon isolation
            brief=brief,
            acceptance=acceptance_cmd or repo.acceptance,
            status="started",
        )
        self.registry.save(task)
        return task, backend, repo

    async def admit_async(
        self, **kwargs: Any
    ) -> tuple[CodingTask, CodingBackend, RepoConfig]:
        """``admit`` plus the checks that need git: worktree vs ``direct`` mode, consent, lock."""
        task, backend, repo = self.admit(**kwargs)
        try:
            self._check_backend_allowed(backend)
            await self._choose_mode(task, repo)
        except DirectConfirmationError as exc:
            session = _lookup_session(task.session_key)
            if session is not None:
                set_pending_direct(session, exc.path)  # the UI asks the user, not the model
            self._fail_admission(task, exc)
            raise
        except Exception as exc:
            self._fail_admission(task, exc)
            raise
        return task, backend, repo

    def _fail_admission(self, task: CodingTask, exc: Exception) -> None:
        task.status = "error"
        task.error = str(exc)
        task.finished_at = time.time()
        self.registry.save(task)  # releases the concurrency slot taken by admit

    def _check_backend_allowed(self, backend: CodingBackend) -> None:
        """Refuse early (and say how to fix it) when the harness may not run unsandboxed."""
        check = getattr(backend, "_check_sandbox_admission", None)
        if check is None:
            return
        try:
            check()
        except PermissionError as exc:
            raise ProjectError(
                f"{exc} To allow it, open Settings > Capabilities > Coworker > Coding and enable "
                f"'run without an OS sandbox' for {backend.name}, or set coding.sandbox."
            ) from exc

    async def _choose_mode(self, task: CodingTask, repo: RepoConfig) -> None:
        kind = await self.workspace_mgr.project_kind(repo)
        if kind.has_worktree_support:
            return
        project = Path(repo.path).expanduser().resolve()
        why = "is a git repository without any commit yet" if kind.kind == "git_empty" else (
            "is not a git repository"
        )
        policy = self.config.coding.non_git
        if policy == "refuse":
            raise ProjectError(
                f"'{project}' {why}, and coding.non_git is 'refuse'. Make it a git repository "
                "(for a new repository, commit once) or change coding.non_git."
            )
        if policy == "ask" and not direct_allowed(_lookup_session(task.session_key), project):
            raise DirectConfirmationError(
                project,
                f"'{project}' {why}, so the coding agent would edit its files in place "
                "(no branch to merge; a snapshot is kept so the changes can be undone). "
                "Ask the user to confirm in the chat UI, or to run `/code direct allow`.",
            )
        if self.registry.count_active_direct(project):
            raise ProjectError(
                f"Another direct coding task is already editing '{project}'. "
                "Wait for it to finish or abort it."
            )
        task.mode = "direct"  # no await since the check above, so two admissions cannot both pass
        task.workdir = str(project)
        task.branch = ""
        task.base = ""
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
        """Run the full coding task workflow delegating to the Phase-based CodingOrchestrator."""
        return await self.orchestrator.execute_task(
            task,
            backend,
            repo,
            files=files,
            wait=wait,
        )

    async def _execute_task_legacy(
        self,
        task: CodingTask,
        backend: CodingBackend,
        repo: RepoConfig,
        *,
        files: list[str] | None = None,
        wait: bool = False,
    ) -> str:
        """Run the full coding task workflow from isolation to verification and delivery."""
        # 1. Isolate: a git worktree, or (direct mode) a snapshot of the project we edit in place
        is_direct = task.mode == "direct"
        before: direct_mod.Manifest | None = None
        try:
            if is_direct:
                snapshot_dir = self.workspace_mgr.worktree_base / task.id / "snapshot"
                before = await asyncio.to_thread(
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
            logger.exception(f"Task {task.id} setup failed: {exc}")
            task.status = "error"
            task.error = f"Setup failed: {exc}"
            task.finished_at = time.time()
            self.registry.save(task)
            return await self._deliver(task, wait)
        run_dir = task.run_dir
        task.status = "running"
        self.registry.save(task)
        self._active_backends[task.id] = backend

        rules = render_rules(task.acceptance)
        rendered_brief = render_brief(task.brief, files)

        wall_timeout_seconds = self.config.coding.timeout_minutes * 60
        idle_timeout_seconds = self.config.coding.idle_timeout_minutes * 60
        progress_throttle = self.config.coding.progress_every_seconds

        start_time = time.time()
        last_progress_time = start_time
        fix_rounds_left = self.config.coding.fix_rounds
        total_tools = 0
        rounds = 1
        task.live = {"tool_count": 0, "last_tool": None, "last_event_at": start_time, "rounds": rounds}

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

        try:
            # Launch first round
            run = backend.start(
                brief=rendered_brief,
                cwd=run_dir,
                rules=rules,
                task_id=task.id,
            )

            while True:
                tool_count = 0
                last_tool: str | None = None
                round_done = False

                last_event_time = time.time()
                timeout_reason: str | None = None

                async def _watchdog() -> None:
                    nonlocal timeout_reason
                    while True:
                        await asyncio.sleep(0.5)
                        now = time.time()
                        if now - start_time > wall_timeout_seconds:
                            timeout_reason = "wall"
                            logger.warning(f"Task {task.id} timed out (wall clock)")
                            task.status = "timed_out"
                            task.error = f"Wall clock timeout ({self.config.coding.timeout_minutes} minutes) exceeded"
                            await backend.abort()
                            break
                        if now - last_event_time > idle_timeout_seconds:
                            timeout_reason = "idle"
                            logger.warning(f"Task {task.id} timed out (idle)")
                            task.status = "timed_out"
                            task.error = f"Idle timeout ({self.config.coding.idle_timeout_minutes} minutes without events) exceeded"
                            await backend.abort()
                            break

                watchdog_task = asyncio.create_task(_watchdog())
                try:
                    async for event in run:
                        now = time.time()
                        last_event_time = now
                        task.live["last_event_at"] = now

                        if isinstance(event, BackendEventTool):
                            if event.state == "start":
                                tool_count += 1
                                total_tools += 1
                                last_tool = event.tool_name
                                task.live["tool_count"] = total_tools
                                task.live["last_tool"] = last_tool

                        if isinstance(event, BackendEventProgress):
                            # Progress throttled reporting
                            if now - last_progress_time >= progress_throttle:
                                elapsed_min = int((now - start_time) / 60)
                                progress_msg = f"🛠️ {task.id} [{task.backend}] {last_tool or 'working'} ({tool_count} tools, {elapsed_min}m)"
                                await post_to_chat(channel=task.channel, chat_id=task.chat_id, content=progress_msg)
                                last_progress_time = now

                        if isinstance(event, BackendEventError):
                            task.error = event.error
                            task.raw_error_line = event.raw_line

                        if isinstance(event, BackendEventDone):
                            round_done = True
                            task.resume_ref = event.resume_ref or task.resume_ref
                            task.summary = event.result.summary or task.summary
                            if event.result.stats.total_tokens > 0:
                                task.round_stats.append(event.result.stats.__dict__)
                            if task.status != "timed_out" and event.result.status != "succeeded":
                                task.status = event.result.status
                                task.error = event.result.error
                                task.raw_error_line = event.result.raw_error_line
                            break
                finally:
                    if not watchdog_task.done():
                        watchdog_task.cancel()

                if task.status in ("timed_out", "aborted", "error"):
                    break

                if not round_done:
                    task.status = "error"
                    task.error = task.error or "Harness exited without completing round"
                    break

                # 2. Nanobot verification
                if is_direct and before is not None:
                    changes = await asyncio.to_thread(
                        direct_mod.diff_manifest, before, Path(task.workdir)
                    )
                    task.changes = changes.to_dict()
                    task.diffstat = changes.summary()
                    task.commits = []
                else:
                    worktree_dir = Path(task.worktree)
                    await self.workspace_mgr.commit_uncommitted_changes(worktree_dir, task.backend)
                    task.diffstat = await self.workspace_mgr.get_diffstat(worktree_dir, task.base)
                    task.commits = await self.workspace_mgr.get_commits(worktree_dir, task.base)

                if task.acceptance:
                    passed, acc_out = await self.workspace_mgr.run_acceptance(run_dir, task.acceptance)
                    task.acceptance_output = acc_out
                    if passed:
                        task.status = "succeeded"
                        break
                    elif fix_rounds_left > 0 and task.resume_ref:
                        fix_rounds_left -= 1
                        rounds += 1
                        task.live["rounds"] = rounds
                        logger.info(f"Acceptance failed for task {task.id}; launching fix round ({fix_rounds_left} remaining)")
                        fu_prompt = render_acceptance_failure_prompt(task.acceptance, acc_out)
                        run = backend.follow_up(
                            run_ref=task.resume_ref,
                            message=fu_prompt,
                            cwd=run_dir,
                            rules=rules,
                            task_id=task.id,
                        )
                        continue
                    else:
                        task.status = "failed_acceptance"
                        break
                else:
                    task.status = "succeeded"
                    break

        except Exception as e:
            logger.exception(f"Unhandled error in task {task.id}: {e}")
            task.status = "error"
            task.error = str(e)
        finally:
            self._active_backends.pop(task.id, None)
            if watch is not None:
                await self._check_outside_writes(task, watch)
            # Accumulate total stats
            total_stats = BackendStats()
            for r in task.round_stats:
                total_stats = total_stats.add(BackendStats(**r))
            task.stats = total_stats.__dict__
            task.finished_at = time.time()
            self.registry.save(task)

        return await self._deliver(task, wait)

    async def _check_outside_writes(self, task: CodingTask, watch: guard.WriteWatch) -> None:
        """Record files the harness changed outside its project; optionally fail the task."""
        try:
            report = await asyncio.to_thread(watch.check)
        except Exception:
            logger.exception(f"Task {task.id}: outside-write check failed")
            return
        if not report:
            return
        task.outside_writes = report.lines()
        logger.warning(
            f"Task {task.id} changed files outside its project: {task.outside_writes}"
        )
        if report.critical and self.config.coding.outside_writes == "fail":
            if task.status == "succeeded":
                task.status = "error"
            note = "The harness modified sensitive files outside the project directory."
            task.error = f"{task.error} {note}" if task.error else note

    async def _deliver(self, task: CodingTask, wait: bool) -> str:
        # 3. Deliver result
        result_text = self._format_delivery_message(task)
        if not wait:
            await inject_turn(
                session_key=task.session_key,
                channel=task.channel,
                chat_id=task.chat_id,
                content=result_text,
                kind="coding_result",
                extra={"task_id": task.id},
            )
        return result_text

    def _format_delivery_message(self, task: CodingTask) -> str:
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

    def _direct_manifest(self, task: CodingTask) -> direct_mod.Manifest:
        manifest = direct_mod.load_manifest(Path(task.snapshot)) if task.snapshot else None
        if manifest is None:
            raise RuntimeError(f"The snapshot of task '{task.id}' is no longer available.")
        return manifest

    async def refresh_direct_changes(self, task: CodingTask) -> direct_mod.Changes:
        """Recompute what a direct task changed (after a resumed round) and store it."""
        manifest = self._direct_manifest(task)
        changes = await asyncio.to_thread(direct_mod.diff_manifest, manifest, Path(task.workdir))
        task.changes = changes.to_dict()
        task.diffstat = changes.summary()
        self.registry.save(task)
        return changes

    async def direct_diff_text(self, task: CodingTask, *, limit: int) -> str:
        """Unified diff of a direct task's small text files, read against the snapshot."""
        manifest = self._direct_manifest(task)
        changes = direct_mod.Changes.from_dict(task.changes)
        if not manifest.copied:
            return ""
        return await asyncio.to_thread(
            direct_mod.text_diff, Path(task.snapshot), Path(task.workdir), changes, limit=limit
        )

    async def discard_direct(
        self, task: CodingTask, *, force: bool = False
    ) -> direct_mod.RestoreResult:
        """Undo a direct task from its snapshot. Never removes the project directory itself."""
        if task.mode != "direct":
            raise RuntimeError(f"Task '{task.id}' did not edit in place.")
        if task.status in ("started", "running"):
            raise RuntimeError(f"Task '{task.id}' is still running; abort it first.")
        manifest = self._direct_manifest(task)
        changes = direct_mod.Changes.from_dict(task.changes)
        result = await asyncio.to_thread(
            direct_mod.restore,
            manifest,
            Path(task.snapshot),
            Path(task.workdir),
            changes,
            since=task.finished_at or time.time(),
            force=force,
        )
        if not result.skipped:
            task.status = "aborted"
            task.changes = {}
            task.diffstat = "undone"
            self.registry.save(task)
        return result

    async def steer(self, task_id: str, message: str) -> None:
        backend = self._active_backends.get(task_id)
        if not backend:
            raise RuntimeError(f"Task '{task_id}' is not currently running.")
        if not backend.capabilities.steer:
            raise NotImplementedError(
                f"Backend '{backend.name}' does not support mid-run steering; use abort then /code resume <id> <message>"
            )
        await backend.steer(message)

    async def abort(self, task_id: str) -> None:
        backend = self._active_backends.get(task_id)
        if backend:
            await backend.abort()
        task = self.registry.get(task_id)
        if task and task.status in ("started", "running"):
            task.status = "aborted"
            self.registry.save(task)
