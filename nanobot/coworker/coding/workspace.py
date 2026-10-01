"""Git worktree lifecycle and workspace isolation."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

if TYPE_CHECKING:
    from nanobot.coworker.config import CodingAgentConfig, RepoConfig


class WorkspaceError(Exception):
    """Raised when repository or worktree operations fail."""


@dataclass(frozen=True)
class ProjectKind:
    """What a project directory is, as far as git is concerned.

    ``git``: the directory is a repository root with at least one commit.
    ``git_subdir``: it sits inside a repository (``toplevel``); ``rel`` is the path below it.
    ``git_empty``: a repository without any commit yet (no worktree can be created).
    ``non_git``: not under version control (or git is unavailable).
    """

    kind: Literal["git", "git_subdir", "git_empty", "non_git"]
    toplevel: Path | None = None
    rel: str = ""

    @property
    def has_worktree_support(self) -> bool:
        return self.kind in ("git", "git_subdir")


async def inspect_project(path: str | Path) -> ProjectKind:
    """Classify ``path`` with git; never raises (missing git counts as ``non_git``)."""
    project = Path(path).expanduser().resolve()
    try:
        code, out = await _run_cmd(["git", "rev-parse", "--show-toplevel"], cwd=project)
    except (OSError, ValueError):
        return ProjectKind("non_git")
    if code != 0 or not out.strip():
        return ProjectKind("non_git")
    toplevel = Path(out.strip().splitlines()[-1]).resolve()
    try:
        code, _ = await _run_cmd(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=project)
    except (OSError, ValueError):
        return ProjectKind("non_git")
    if code != 0:
        return ProjectKind("git_empty", toplevel)
    rel = os.path.relpath(project, toplevel)
    if rel in (".", ""):
        return ProjectKind("git", toplevel)
    if rel.startswith(".."):  # symlinked layout we cannot map; treat as unsupported
        return ProjectKind("non_git")
    return ProjectKind("git_subdir", toplevel, Path(rel).as_posix())


async def _run_cmd(
    cmd: list[str] | str,
    *,
    cwd: Path | str,
    is_shell: bool = False,
    timeout: float = 60.0,
) -> tuple[int, str]:
    if is_shell:
        proc = await asyncio.create_subprocess_shell(
            str(cmd),
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    else:
        args = cmd if isinstance(cmd, list) else [cmd]
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        code = proc.returncode or 0
        out_str = stdout.decode("utf-8", errors="replace")
        return code, out_str
    except (asyncio.TimeoutError, TimeoutError):
        try:
            proc.kill()
        except Exception:
            pass
        return -1, "Command timed out"


class WorkspaceManager:
    """Manages git worktrees, verification commands, and merges."""

    def __init__(
        self,
        config: CodingAgentConfig,
        workspace_root: Path,
    ) -> None:
        self.config = config
        self.workspace_root = workspace_root
        self.worktree_base = (
            Path(config.worktree_root).expanduser()
            if config.worktree_root
            else workspace_root / ".coworker" / "code-worktrees"
        )
        self.worktree_base.mkdir(parents=True, exist_ok=True)

    def validate_repo(self, repo_path: str | Path) -> RepoConfig:
        """Verify that the target path resolves to an explicitly configured repo."""
        resolved = Path(repo_path).expanduser().resolve()
        for r in self.config.repos:
            cfg_resolved = Path(r.path).expanduser().resolve()
            if resolved == cfg_resolved:
                return r
        raise WorkspaceError(
            f"Repository '{repo_path}' is not in the allowed coding.repos list: "
            f"{[r.path for r in self.config.repos]}"
        )

    def validate_task_repo(self, task_repo: str | Path) -> RepoConfig:
        """Repo of a task this system already admitted (it is in the registry, so it is trusted).

        Unlike :meth:`validate_repo` this does not require the path to be in ``coding.repos``:
        the project may have been the directory the user picked for the chat. A matching
        ``coding.repos`` entry still supplies its profile.
        """
        key = os.path.normcase(str(Path(task_repo).expanduser().resolve()))
        for r in self.config.repos:
            if os.path.normcase(str(Path(r.path).expanduser().resolve())) == key:
                return r
        from nanobot.coworker.config import RepoConfig

        return RepoConfig(path=str(task_repo))

    async def create_worktree(
        self,
        *,
        repo: RepoConfig,
        task_id: str,
        base_ref: str | None = None,
    ) -> tuple[Path, str]:
        """Create a dedicated git worktree and branch for the task."""
        project_dir = Path(repo.path).expanduser().resolve()
        info = await inspect_project(project_dir)
        if info.kind == "git_empty":
            raise WorkspaceError(
                f"'{project_dir}' is a git repository without any commit yet; "
                "make an initial commit so a worktree can be created."
            )
        if info.toplevel is None or not info.has_worktree_support:
            raise WorkspaceError(f"'{project_dir}' is not inside a git repository.")
        repo_dir = info.toplevel  # worktrees are always cut from the repository root

        base = base_ref or repo.base_ref or "HEAD"
        branch_name = f"coworker/code/{task_id}"
        worktree_dir = self.worktree_base / task_id

        if worktree_dir.exists():
            shutil.rmtree(worktree_dir, ignore_errors=True)

        add_cmd = ["git", "worktree", "add", "-b", branch_name, str(worktree_dir), base]
        code, out = await _run_cmd(add_cmd, cwd=repo_dir)
        if code != 0:
            raise WorkspaceError(f"Failed to create worktree for task {task_id}: {out}")

        return worktree_dir, branch_name

    async def commit_uncommitted_changes(self, worktree: Path, backend_name: str) -> bool:
        """Check for uncommitted files in the worktree and commit them if any."""
        code, out = await _run_cmd(["git", "status", "--porcelain"], cwd=worktree)
        if code == 0 and out.strip():
            logger.info(f"Committing uncommitted changes from {backend_name} in {worktree}")
            await _run_cmd(["git", "add", "-A"], cwd=worktree)
            await _run_cmd(
                ["git", "commit", "-m", f"coworker: uncommitted changes from {backend_name}"],
                cwd=worktree,
            )
            return True
        return False

    async def get_diffstat(self, worktree: Path, base_ref: str) -> str:
        code, out = await _run_cmd(["git", "diff", "--stat", f"{base_ref}...HEAD"], cwd=worktree)
        return out.strip() if code == 0 else ""

    async def get_full_diff(self, worktree: Path, base_ref: str) -> str:
        code, out = await _run_cmd(["git", "diff", f"{base_ref}...HEAD"], cwd=worktree)
        return out if code == 0 else ""

    async def get_commits(self, worktree: Path, base_ref: str) -> list[str]:
        code, out = await _run_cmd(["git", "log", "--oneline", f"{base_ref}..HEAD"], cwd=worktree)
        if code != 0 or not out.strip():
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    async def project_kind(self, repo: RepoConfig) -> ProjectKind:
        return await inspect_project(repo.path)

    async def run_acceptance(
        self,
        worktree: Path,
        cmd: str,
        *,
        timeout: float = 300.0,
    ) -> tuple[bool, str]:
        """Execute the acceptance command in the worktree."""
        code, out = await _run_cmd(cmd, cwd=worktree, is_shell=True, timeout=timeout)
        return code == 0, out

    async def merge(
        self,
        *,
        repo: RepoConfig,
        task_id: str,
        base_ref: str,
        strategy: Literal["squash", "no-ff", "ff-only"] = "squash",
        commit_message: str = "",
    ) -> tuple[bool, str]:
        """Merge task branch into repo main checkout if on base branch and clean."""
        repo_dir = Path(repo.path).expanduser().resolve()
        branch_name = f"coworker/code/{task_id}"

        # 1. Check current branch in main checkout
        code, branch_out = await _run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)
        cur_branch = branch_out.strip()
        if code != 0 or (base_ref != "HEAD" and cur_branch != base_ref):
            return False, (
                f"Cannot merge: main checkout is on branch '{cur_branch}', expected '{base_ref}'. "
                "Please switch to the target branch first."
            )

        # 2. Check clean working tree
        code, status_out = await _run_cmd(["git", "status", "--porcelain"], cwd=repo_dir)
        if code != 0 or status_out.strip():
            return False, (
                "Cannot merge: main checkout has uncommitted or unstaged changes. "
                "Please commit or stash them first."
            )

        # 3. Perform merge
        if strategy == "squash":
            code, out = await _run_cmd(["git", "merge", "--squash", branch_name], cwd=repo_dir)
            if code != 0:
                await _run_cmd(["git", "merge", "--abort"], cwd=repo_dir)
                return False, f"Merge conflict or failure during squash: {out}"
            msg = commit_message or f"coworker: completed task {task_id}"
            code, out = await _run_cmd(["git", "commit", "-m", msg], cwd=repo_dir)
            if code != 0:
                return False, f"Failed to commit squashed merge: {out}"
        elif strategy == "ff-only":
            code, out = await _run_cmd(["git", "merge", "--ff-only", branch_name], cwd=repo_dir)
            if code != 0:
                return False, f"Fast-forward merge failed: {out}"
        else:  # no-ff
            msg = commit_message or f"coworker: merge task {task_id}"
            code, out = await _run_cmd(["git", "merge", "--no-ff", branch_name, "-m", msg], cwd=repo_dir)
            if code != 0:
                await _run_cmd(["git", "merge", "--abort"], cwd=repo_dir)
                return False, f"Merge failed: {out}"

        # 4. Cleanup worktree and branch
        await self.cleanup(repo=repo, task_id=task_id, delete_branch=self.config.delete_branch_after_merge)
        return True, "Merge succeeded."

    async def cleanup(
        self,
        *,
        repo: RepoConfig,
        task_id: str,
        delete_branch: bool = True,
    ) -> None:
        repo_dir = Path(repo.path).expanduser().resolve()
        branch_name = f"coworker/code/{task_id}"
        worktree_dir = self.worktree_base / task_id

        # Remove worktree
        if worktree_dir.exists():
            await _run_cmd(["git", "worktree", "remove", "--force", str(worktree_dir)], cwd=repo_dir)
            shutil.rmtree(worktree_dir, ignore_errors=True)

        # Delete branch
        if delete_branch:
            await _run_cmd(["git", "branch", "-D", branch_name], cwd=repo_dir)

    async def prune_expired(self, max_days: int) -> None:
        """Prune failed worktree directories older than max_days."""
        if max_days <= 0 or not self.worktree_base.exists():
            return
        now = time.time()
        max_age_seconds = max_days * 86400
        for item in self.worktree_base.iterdir():
            if item.is_dir():
                try:
                    mtime = item.stat().st_mtime
                    if now - mtime > max_age_seconds:
                        logger.info(f"Pruning expired worktree {item}")
                        shutil.rmtree(item, ignore_errors=True)
                except Exception as e:
                    logger.debug(f"Failed pruning worktree {item}: {e}")
