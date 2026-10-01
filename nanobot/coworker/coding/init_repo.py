"""Turn a plain project folder into a git repository, only after the user has seen what goes in.

``plan_init`` never touches the project: it lists what *would* be committed using a throw-away git
directory pointed at the folder. ``run_init`` redoes the plan, refuses to continue if it no longer
matches the one the user reviewed (``digest``), then runs ``git init``, writes ignore rules and makes
the first commit. If anything fails, what we created (``.git``, ``.gitignore``) is removed again.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

GIT_TIMEOUT_S = 120
MAX_FILES = 10_000
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
LARGE_FILE_BYTES = 20 * 1024 * 1024
PREVIEW_FILES = 200

# Proposed ignore rules: caches / build output, OS junk, and files that usually hold secrets.
HEAVY_DIRS = (
    "node_modules/", ".venv/", "venv/", "__pycache__/", "dist/", "build/", ".cache/", ".next/",
    ".nuxt/", ".mypy_cache/", ".pytest_cache/", ".ruff_cache/", ".tox/",
)
JUNK = (".DS_Store", "Thumbs.db")
SENSITIVE = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", "id_rsa", "id_rsa.*",
    "id_ed25519", "id_ed25519.*", "secrets.*", "credentials.json",
)
PROPOSED_PATTERNS = (*HEAVY_DIRS, *JUNK, *SENSITIVE)


class InitError(RuntimeError):
    """The folder cannot (or must not) be turned into a repository right now."""


@dataclass
class InitPlan:
    path: Path
    files: list[str] = field(default_factory=list)  # what the first commit will contain
    total_bytes: int = 0
    gitignore_text: str | None = None  # contents of a new .gitignore; None when one exists already
    extra_excludes: list[str] = field(default_factory=list)  # applied via .git/info/exclude
    skipped_sensitive: list[str] = field(default_factory=list)
    skipped_large: list[str] = field(default_factory=list)
    skipped_embedded: list[str] = field(default_factory=list)
    existing_repo: bool = False  # already `git init`-ed but without a commit
    digest: str = ""

    def preview(self) -> dict[str, object]:
        """Compact, JSON-safe view for status / UI."""
        return {
            "path": str(self.path),
            "digest": self.digest,
            "file_count": len(self.files),
            "files": self.files[:PREVIEW_FILES],
            "total_mb": round(self.total_bytes / (1024 * 1024), 1),
            "gitignore": self.gitignore_text,
            "extra_excludes": self.extra_excludes,
            "skipped_sensitive": self.skipped_sensitive[:20],
            "skipped_large": self.skipped_large[:20],
            "skipped_embedded": self.skipped_embedded[:20],
            "existing_repo": self.existing_repo,
        }


def _git(
    args: list[str],
    *,
    cwd: Path,
    git_dir: Path | None = None,
    no_global_excludes: Path | None = None,
    extra_config: list[str] | None = None,
    check: bool = True,
) -> str:
    cmd = ["git"]
    for item in extra_config or []:
        cmd += ["-c", item]
    if no_global_excludes is not None:
        cmd += ["-c", f"core.excludesFile={no_global_excludes}"]
    if git_dir is not None:
        cmd += ["-c", "core.bare=false", f"--git-dir={git_dir}", f"--work-tree={cwd}"]
    cmd += args
    try:
        proc = subprocess.run(  # noqa: S603
            cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=GIT_TIMEOUT_S, stdin=subprocess.DEVNULL, check=False,
        )
    except FileNotFoundError as exc:
        raise InitError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise InitError("git took too long; the folder may be very large") from exc
    if check and proc.returncode != 0:
        raise InitError(f"git {' '.join(args[:2])} failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout


def _is_sensitive(rel: str) -> bool:
    name = rel.rstrip("/").rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in SENSITIVE)


def _check_target(project: Path) -> bool:
    """Validate the folder; returns True when it is an empty repository (no commit yet)."""
    if not project.is_dir():
        raise InitError(f"'{project}' is not a directory")
    top = _git(["rev-parse", "--show-toplevel"], cwd=project, check=False).strip()
    if not top:
        return False
    if Path(top).resolve() != project.resolve():
        raise InitError(
            f"'{project}' is inside the git repository '{top}'. Work from that repository instead "
            "of creating a nested one."
        )
    has_commit = subprocess.run(  # noqa: S603
        ["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=project, capture_output=True,
        stdin=subprocess.DEVNULL, check=False,
    ).returncode == 0
    if has_commit:
        raise InitError(f"'{project}' is already a git repository with commits.")
    return True


def _gitignore_text() -> str:
    lines = ["# Added by nanobot: caches, build output, OS files and likely secrets", *PROPOSED_PATTERNS]
    return "\n".join(lines) + "\n"


def plan_init(project: Path) -> InitPlan:
    """What ``run_init`` would commit; the project folder itself is not modified."""
    project = project.expanduser().resolve()
    existing = _check_target(project)
    has_gitignore = (project / ".gitignore").exists()
    plan = InitPlan(path=project, existing_repo=existing)
    if has_gitignore:
        plan.extra_excludes = list(PROPOSED_PATTERNS)
    else:
        plan.gitignore_text = _gitignore_text()

    with tempfile.TemporaryDirectory(prefix="nanobot-init-") as tmp:
        tmp_dir = Path(tmp)
        git_dir = tmp_dir / "g"
        _git(["init", "-q", "--bare", str(git_dir)], cwd=tmp_dir)
        empty = tmp_dir / "no-global-excludes"
        empty.write_text("", encoding="utf-8")
        exclude_file = git_dir / "info" / "exclude"
        exclude_file.parent.mkdir(parents=True, exist_ok=True)

        def listing(extra: list[str]) -> list[str]:
            exclude_file.write_text("\n".join([*PROPOSED_PATTERNS, *extra]) + "\n", encoding="utf-8")
            out = _git(
                ["ls-files", "-o", "--exclude-standard", "-z"],
                cwd=project, git_dir=git_dir, no_global_excludes=empty,
            )
            return sorted(p for p in out.split("\0") if p)

        extra: list[str] = []
        files = listing(extra)
        embedded = [p for p in files if p.endswith("/")]
        if embedded:  # a nested repository would be committed as an opaque link
            extra += [f"/{p}" for p in embedded]
            plan.skipped_embedded = embedded
            files = listing(extra)
        sizes: dict[str, int] = {}
        for rel in files:
            try:
                sizes[rel] = (project / rel).stat().st_size
            except OSError:
                sizes[rel] = 0
        large = [rel for rel, size in sizes.items() if size > LARGE_FILE_BYTES]
        if large:
            extra += [f"/{p}" for p in large]
            plan.skipped_large = large
            files = listing(extra)
            sizes = {rel: sizes.get(rel, 0) for rel in files}
        ignored = _git(
            ["ls-files", "-o", "-i", "--exclude-standard", "--directory", "-z"],
            cwd=project, git_dir=git_dir, no_global_excludes=empty,
        )
        plan.skipped_sensitive = sorted({p for p in ignored.split("\0") if p and _is_sensitive(p)})

    if len(files) > MAX_FILES:
        raise InitError(
            f"{len(files)} files would be committed (limit {MAX_FILES}). Add large folders to a "
            ".gitignore first, then run this again."
        )
    total = sum(sizes.get(f, 0) for f in files)
    if total > MAX_TOTAL_BYTES:
        raise InitError(
            f"{round(total / 1024 / 1024)} MB would be committed (limit {MAX_TOTAL_BYTES // 1024 // 1024} MB). "
            "Exclude large files with a .gitignore first."
        )
    if not files and plan.gitignore_text is None:
        raise InitError("There is nothing to commit in this folder.")
    plan.files = files
    plan.total_bytes = total
    if has_gitignore:
        plan.extra_excludes = [*PROPOSED_PATTERNS, *extra]
    elif extra:
        plan.gitignore_text = (plan.gitignore_text or "") + "\n".join(extra) + "\n"
    digest = hashlib.sha256()
    for rel in files:
        digest.update(f"{rel}:{sizes.get(rel, 0)}\n".encode())
    digest.update((plan.gitignore_text or "").encode())
    digest.update("\n".join(plan.extra_excludes).encode())
    plan.digest = digest.hexdigest()
    return plan


def run_init(project: Path, expected_digest: str) -> tuple[str, int]:
    """Create the repository and its first commit; returns (short commit hash, file count)."""
    plan = plan_init(project)
    if plan.digest != expected_digest:
        raise InitError("The folder changed since the preview. Review the new list and confirm again.")
    root = plan.path
    created_git = not (root / ".git").exists()
    created_ignore = False
    with tempfile.TemporaryDirectory(prefix="nanobot-init-") as tmp:
        empty = Path(tmp) / "no-global-excludes"
        empty.write_text("", encoding="utf-8")
        try:
            if created_git:
                try:
                    _git(["init", "-q", "-b", "main"], cwd=root)
                except InitError:  # git older than 2.28 has no -b
                    _git(["init", "-q"], cwd=root)
                    _git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=root)
            if plan.gitignore_text is not None:
                (root / ".gitignore").write_text(plan.gitignore_text, encoding="utf-8")
                created_ignore = True
            else:
                info = root / ".git" / "info"
                info.mkdir(parents=True, exist_ok=True)
                with (info / "exclude").open("a", encoding="utf-8") as handle:
                    handle.write("\n# Added by nanobot\n" + "\n".join(plan.extra_excludes) + "\n")
            _git(["add", "-A"], cwd=root, no_global_excludes=empty)
            staged = {p for p in _git(["diff", "--cached", "--name-only", "-z"], cwd=root).split("\0") if p}
            expected: set[str] = set(plan.files)
            if created_ignore:
                expected.add(".gitignore")
            if staged != expected:
                raise InitError(
                    "The files to commit differ from the preview. Nothing was committed; review again."
                )
            identity: list[str] = []
            if not _git(["config", "user.name"], cwd=root, check=False).strip():
                identity += ["user.name=nanobot"]
            if not _git(["config", "user.email"], cwd=root, check=False).strip():
                identity += ["user.email=nanobot@localhost"]
            _git(
                ["commit", "-q", "-m", "Initial commit (created by nanobot)"],
                cwd=root, extra_config=[*identity, "commit.gpgsign=false"],
            )
            commit = _git(["rev-parse", "--short", "HEAD"], cwd=root).strip()
        except Exception:
            _undo(root, created_git=created_git, created_ignore=created_ignore)
            raise
    return commit, len(staged)


def _remove_git_dir(git_dir: Path) -> None:
    """Delete a ``.git`` we created. Git marks object files read-only, which blocks ``rmtree`` on Windows."""

    def make_writable_and_retry(func: Callable[..., object], path: str, _exc: object) -> None:
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(git_dir, onexc=make_writable_and_retry)
    else:  # pragma: no cover - python 3.11
        shutil.rmtree(git_dir, onerror=make_writable_and_retry)


def _undo(root: Path, *, created_git: bool, created_ignore: bool) -> None:
    """Remove only what ``run_init`` itself created."""
    if created_ignore:
        try:
            (root / ".gitignore").unlink()
        except OSError:
            pass
    git_dir = root / ".git"
    if created_git and git_dir.is_dir() and git_dir.parent == root:
        _remove_git_dir(git_dir)


def format_plan(plan: InitPlan) -> str:
    """Human-readable preview for the `/code init` reply."""
    shown = plan.files[:30]
    lines = [
        f"📦 **Create a git repository in** `{plan.path}`",
        f"The first commit will contain **{len(plan.files)} file(s)** (~{plan.total_bytes / 1024 / 1024:.1f} MB):",
        "```",
        *shown,
        *( [f"… and {len(plan.files) - len(shown)} more"] if len(plan.files) > len(shown) else [] ),
        "```",
    ]
    if plan.gitignore_text is not None:
        lines += ["A new `.gitignore` will be created:", "```", plan.gitignore_text.strip(), "```"]
    else:
        lines.append("Your existing `.gitignore` is kept; extra rules go to `.git/info/exclude`.")
    if plan.skipped_sensitive:
        lines.append("Left out (looks like secrets): " + ", ".join(f"`{p}`" for p in plan.skipped_sensitive[:10]))
    if plan.skipped_large:
        lines.append("Left out (over 20 MB): " + ", ".join(f"`{p}`" for p in plan.skipped_large[:10]))
    if plan.skipped_embedded:
        lines.append("Left out (separate git repositories): " + ", ".join(f"`{p}`" for p in plan.skipped_embedded[:10]))
    lines.append("")
    lines.append("Nothing has been changed yet. Run `/code init confirm` to create it, or `/code init cancel`.")
    return "\n".join(lines)

