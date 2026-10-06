"""Driver managing the lifecycle of coding tasks on the Pi v2 runtime."""

from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.coworker.coding import direct as direct_mod
from nanobot.coworker.coding.backends.base import sandbox_policy_for
from nanobot.coworker.coding.orchestrator import CodingOrchestrator
from nanobot.coworker.coding.pi.client import PiClient
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
from nanobot.coworker.runtime import get_session

if TYPE_CHECKING:
    from nanobot.coworker.config import CoworkerConfig, RepoConfig


# Running clients by task id, shared by every runner instance so steer/abort issued from a later
# tool call or `/code` command reaches the process started by an earlier one.
_ACTIVE_CLIENTS: dict[str, PiClient] = {}


def _lookup_session(session_key: str) -> Any | None:
    """Session of the task's chat; None when unavailable (falls back to ``coding.repos``)."""
    try:
        return get_session(session_key)
    except Exception:
        logger.debug("coding: session lookup failed for {}; using coding.repos", session_key)
        return None


class CodingRunner:
    """Orchestrates coding tasks across workspace isolation, the Pi runtime, and verification."""

    def __init__(self, config: CoworkerConfig, workspace_root: Path) -> None:
        self.config = config
        self.workspace_root = workspace_root
        self.workspace_mgr = WorkspaceManager(config.coding, workspace_root)
        self.registry = shared_registry(workspace_root)
        self._active_backends = _ACTIVE_CLIENTS
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
    ) -> tuple[CodingTask, PiClient, RepoConfig]:
        """Validate prerequisites, allocate task id, and prepare a Pi client for the task."""
        if not self.config.coding.enabled:
            raise RuntimeError("coding_agent is disabled in configuration (coding.enabled is False).")

        # Resolve the project: the directory the user picked for this chat, else coding.repos.
        project = resolve_project(_lookup_session(session_key), self.config.coding, repo_path)
        repo = project.repo_config

        # Agy was removed; any configured backend resolves to Pi.
        resolved_backend_name = (
            backend_name or getattr(repo, "backend", None) or getattr(self.config.coding, "default_backend", "pi") or "pi"
        ).strip().lower()
        if resolved_backend_name != "pi":
            logger.warning(f"coding backend '{resolved_backend_name}' is no longer supported; using 'pi'")
            resolved_backend_name = "pi"

        # Check binary availability
        cmd_prefix = self.config.coding.pi.command
        binary = cmd_prefix[0] if cmd_prefix else "pi"
        # With coding.sandbox='wsl' the harness runs inside the distro; the sandbox checks it there.
        if (
            self.config.coding.sandbox != "wsl"
            and not shutil.which(binary)
            and not Path(binary).exists()
        ):
            raise RuntimeError(
                f"Pi binary '{binary}' is not installed or not found on PATH. "
                "Please install and log in to Pi in a terminal first."
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
        client = PiClient(
            config=self.config.coding.pi,
            sandbox_policy=sandbox_policy_for(self.config),
            timeout_minutes=self.config.coding.timeout_minutes,
            idle_timeout_minutes=self.config.coding.idle_timeout_minutes,
        )

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
        return task, client, repo

    async def admit_async(
        self, **kwargs: Any
    ) -> tuple[CodingTask, PiClient, RepoConfig]:
        """``admit`` plus the checks that need git: worktree vs ``direct`` mode, consent, lock."""
        task, client, repo = self.admit(**kwargs)
        try:
            self._check_backend_allowed(client)
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
        return task, client, repo

    def _fail_admission(self, task: CodingTask, exc: Exception) -> None:
        task.status = "error"
        task.error = str(exc)
        task.finished_at = time.time()
        self.registry.save(task)  # releases the concurrency slot taken by admit

    def _check_backend_allowed(self, client: PiClient) -> None:
        """Refuse early (and say how to fix it) when Pi may not run unsandboxed."""
        try:
            client.check_sandbox_admission()
        except PermissionError as exc:
            raise ProjectError(
                f"{exc} To allow it, open Settings > Capabilities > Coworker > Coding and enable "
                "'run without an OS sandbox' for pi, or set coding.sandbox."
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
                f"'{project}' {why}, and coding.non_git is 'refuse'. Run `/code init` to create a "
                "git repository (then commit once) so the agent can work in an isolated worktree, "
                "or change coding.non_git."
            )
        if policy == "ask" and not direct_allowed(_lookup_session(task.session_key), project):
            raise DirectConfirmationError(
                project,
                f"'{project}' {why}, so the coding agent would edit its files in place "
                "(no branch to merge; a snapshot is kept so the changes can be undone). "
                "Ask the user to confirm in the chat UI, run `/code direct allow`, "
                "or run `/code init` to create a git repository for worktree isolation.",
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
        client: PiClient,
        repo: RepoConfig,
        *,
        files: list[str] | None = None,
        wait: bool = False,
    ) -> str:
        """Run the full coding task workflow delegating to the Phase-based CodingOrchestrator."""
        return await self.orchestrator.execute_task(
            task,
            client,
            repo,
            files=files,
            wait=wait,
        )

    def _new_client(self) -> PiClient:
        return PiClient(
            config=self.config.coding.pi,
            sandbox_policy=sandbox_policy_for(self.config),
            timeout_minutes=self.config.coding.timeout_minutes,
            idle_timeout_minutes=self.config.coding.idle_timeout_minutes,
        )

    async def resume(self, task: CodingTask, *, message: str | None = None, wait: bool = False) -> str:
        """Resume an interrupted task with a fresh Pi client, phase-aware."""
        return await self.orchestrator.resume_task(task, self._new_client(), message=message, wait=wait)

    def claim_approval(self, task_id: str) -> CodingTask:
        """Atomically take an awaiting-approval task so a second approve/revise is a no-op."""
        task = self.registry.get(task_id)
        if task is None:
            raise RuntimeError(f"Task '{task_id}' not found.")
        if task.status != "awaiting_approval":
            raise RuntimeError(
                f"Task '{task_id}' is not awaiting plan approval (status={task.status}, phase={task.phase})."
            )
        if task.id in self._active_backends:
            raise RuntimeError(f"Task '{task_id}' is already running.")
        task.status = "running"
        task.error = None
        task.finished_at = 0.0
        self.registry.save(task)
        return task

    def _fail_continuation(self, task: CodingTask, exc: Exception) -> None:
        task.status = "error"
        task.error = str(exc)
        task.finished_at = time.time()
        self.registry.save(task)

    async def approve(self, task: CodingTask, *, notes: str | None = None, wait: bool = False) -> str:
        """Continue a parked plan into implement → review → deliver."""
        try:
            return await self.orchestrator.continue_approved_plan(
                task, self._new_client(), notes=notes, wait=wait
            )
        except Exception as exc:
            self._fail_continuation(task, exc)
            raise

    async def revise_plan(self, task: CodingTask, *, feedback: str, wait: bool = False) -> str:
        """Re-run planning with coordinator feedback."""
        try:
            return await self.orchestrator.revise_plan(
                task, self._new_client(), feedback=feedback, wait=wait
            )
        except Exception as exc:
            self._fail_continuation(task, exc)
            raise

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
        client = self._active_backends.get(task_id)
        if not client:
            raise RuntimeError(f"Task '{task_id}' is not currently running.")
        await client.steer(message)

    async def abort(self, task_id: str) -> None:
        client = self._active_backends.get(task_id)
        if client:
            await client.abort()
        task = self.registry.get(task_id)
        if task and task.status in ("started", "running"):
            task.status = "aborted"
            self.registry.save(task)
