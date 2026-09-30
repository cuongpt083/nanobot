"""Backend-neutral driver managing the lifecycle of coding tasks."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

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
from nanobot.coworker.coding.tasks import (
    CodingTask,
    generate_task_id,
    shared_registry,
)
from nanobot.coworker.coding.workspace import WorkspaceManager
from nanobot.coworker.runtime import inject_turn, post_to_chat

if TYPE_CHECKING:
    from nanobot.coworker.config import CoworkerConfig, RepoConfig


# Running backends by task id, shared by every runner instance so steer/abort issued from a later
# tool call or `/code` command reaches the process started by an earlier one.
_ACTIVE_BACKENDS: dict[str, CodingBackend] = {}


class CodingRunner:
    """Orchestrates coding tasks across workspace isolation, harnesses, and verification."""

    def __init__(self, config: CoworkerConfig, workspace_root: Path) -> None:
        self.config = config
        self.workspace_root = workspace_root
        self.workspace_mgr = WorkspaceManager(config.coding, workspace_root)
        self.registry = shared_registry(workspace_root)
        self._active_backends = _ACTIVE_BACKENDS

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

        if not self.config.coding.repos:
            raise RuntimeError("No repositories configured in coding.repos; execution is refused.")

        # Resolve repo
        if repo_path:
            repo = self.workspace_mgr.validate_repo(repo_path)
        elif len(self.config.coding.repos) == 1:
            repo = self.config.coding.repos[0]
        else:
            options = [r.path for r in self.config.coding.repos]
            raise ValueError(f"Ambiguous repository; specify one of: {options}")

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
        if not shutil.which(binary) and not Path(binary).exists():
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

    async def execute_task(
        self,
        task: CodingTask,
        backend: CodingBackend,
        repo: RepoConfig,
        *,
        files: list[str] | None = None,
        wait: bool = False,
    ) -> str:
        """Run the full coding task workflow from isolation to verification and delivery."""
        # 1. Isolate worktree
        worktree_dir, branch_name = await self.workspace_mgr.create_worktree(
            repo=repo,
            task_id=task.id,
            base_ref=task.base,
        )
        task.worktree = str(worktree_dir)
        task.branch = branch_name
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

        try:
            # Launch first round
            run = backend.start(
                brief=rendered_brief,
                cwd=worktree_dir,
                rules=rules,
                task_id=task.id,
            )

            while True:
                tool_count = 0
                last_tool: str | None = None
                last_event_time = time.time()
                round_done = False

                async for event in run:
                    now = time.time()
                    last_event_time = now
                    task.live["last_event_at"] = now

                    # Wall clock timeout
                    if now - start_time > wall_timeout_seconds:
                        logger.warning(f"Task {task.id} timed out (wall clock)")
                        task.status = "timed_out"
                        task.error = f"Wall clock timeout ({self.config.coding.timeout_minutes} minutes) exceeded"
                        await backend.abort()
                        break

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
                        if event.result.status != "succeeded":
                            task.status = event.result.status
                            task.error = event.result.error
                            task.raw_error_line = event.result.raw_error_line
                        break

                    # Idle timeout check
                    if now - last_event_time > idle_timeout_seconds:
                        logger.warning(f"Task {task.id} timed out (idle)")
                        task.status = "timed_out"
                        task.error = f"Idle timeout ({self.config.coding.idle_timeout_minutes} minutes without events) exceeded"
                        await backend.abort()
                        break

                if task.status in ("timed_out", "aborted", "error"):
                    break

                if not round_done:
                    task.status = "error"
                    task.error = task.error or "Harness exited without completing round"
                    break

                # 2. Nanobot verification
                await self.workspace_mgr.commit_uncommitted_changes(worktree_dir, task.backend)
                task.diffstat = await self.workspace_mgr.get_diffstat(worktree_dir, task.base)
                task.commits = await self.workspace_mgr.get_commits(worktree_dir, task.base)

                if task.acceptance:
                    passed, acc_out = await self.workspace_mgr.run_acceptance(worktree_dir, task.acceptance)
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
                            cwd=worktree_dir,
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
            # Accumulate total stats
            total_stats = BackendStats()
            for r in task.round_stats:
                total_stats = total_stats.add(BackendStats(**r))
            task.stats = total_stats.__dict__
            self.registry.save(task)

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

        lines = [
            f"[auto-coding-result] Task `{task.id}` ({task.backend}) finished with status: `{task.status}`",
            f"**Goal**: {task.brief}",
            f"**Harness Summary**: {task.summary or 'None'}",
            f"**Commits**: {len(task.commits)} commit(s) on `{task.branch}`",
            f"**Tokens**: {tokens_info}",
            f"**Acceptance**: {acc_text}",
        ]
        if task.error:
            lines.append(f"**Error**: {task.error}")
        if task.diffstat:
            lines.extend(["**Diffstat**:", "```", task.diffstat, "```"])

        lines.extend([
            "",
            f"Review the results above, then tell the user to `/code merge {task.id}` or `/code discard {task.id}`.",
        ])
        return "\n".join(lines)

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
