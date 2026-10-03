"""Path safety for coding tasks (Windows, Linux, macOS).

Two independent checks, both best-effort defence in depth on top of the worktree/snapshot isolation:

* ``blocked_reason`` — refuse to *start* a harness in a directory that is too broad (filesystem
  root, the user's home, its parents) or that holds system files or credentials.
* ``WriteWatch`` — the harness runs unsandboxed with permissions auto-approved, so it can write
  anywhere the user can. Before the run we record file metadata at the places a task must never
  touch (credentials, shell/startup files, the base repository and its git hooks/config, sibling
  files of a project); afterwards we diff and report anything that changed.

Detection happens after the fact: it reports, it cannot prevent or undo the write.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

# Never scanned (build output, caches, VCS state).
_SKIP_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next", ".nuxt", ".cache",
    }
)

_POSIX_SYSTEM = (
    "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/boot", "/dev", "/proc", "/sys",
    "/run", "/root", "/System", "/Library", "/Applications", "/private/etc",
)
_WINDOWS_ENV = (
    "SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData",
)
# Directories under the user's home that hold credentials, tool state or OS data.
_HOME_PROTECTED = (
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".config", ".local", ".npm", ".cargo",
    ".nanobot", ".claude", ".gemini", ".pi", "AppData", "Library",
)
# Files / directories a task must never modify, relative to the home directory.
_HOME_WATCH = (
    ".ssh", ".gnupg", ".aws", ".kube", ".gitconfig", ".git-credentials", ".netrc", ".npmrc",
    ".bashrc", ".bash_profile", ".bash_login", ".profile", ".zshrc", ".zprofile", ".zshenv",
    ".config/git", ".config/autostart", ".config/systemd/user", ".config/fish/config.fish",
    "Library/LaunchAgents",
    "Documents/PowerShell", "Documents/WindowsPowerShell",
    "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
)

WATCH_MAX_ENTRIES = 20_000
REPORT_MAX = 20


def _key(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def _system_roots() -> list[str]:
    roots: list[str] = []
    if os.name == "nt":
        for name in _WINDOWS_ENV:
            value = os.environ.get(name)
            if value:
                roots.append(_key(value))
    else:
        roots += [_key(p) for p in _POSIX_SYSTEM]
    return roots


def _nanobot_dirs() -> list[str]:
    try:
        from nanobot.config.loader import get_config_path

        return [_key(Path(get_config_path()).expanduser().parent)]
    except Exception:
        return []


def blocked_reason(path: str | Path, extra: Iterable[str] = ()) -> str | None:
    """Why a coding task must not run in ``path``, or None when it is acceptable."""
    resolved = Path(path).expanduser().resolve()
    key = _key(resolved)
    home = Path.home().resolve()
    home_key = _key(home)

    if resolved.parent == resolved:
        return "it is the root of a drive or filesystem"
    if key == home_key or _within(home_key, key):
        return "it is your home directory (or a parent of it); choose a project subfolder"

    for entry in extra:
        if entry and _within(key, _key(entry)):
            return f"it is inside '{entry}', which is listed in coding.blocked_paths"

    if _within(key, _key(tempfile.gettempdir())):
        return None  # scratch space is fine even though it may sit under AppData

    for root in _system_roots():
        if _within(key, root):
            return "it is a system directory"
    for name in _HOME_PROTECTED:
        if _within(key, _key(home / name)):
            return f"it is inside '~/{name}', which holds credentials or tool state"
    for root in _nanobot_dirs():
        if _within(key, root):
            return "it is nanobot's own configuration directory"
    return None


# ---- write detection -------------------------------------------------------------------------

Meta = tuple[int, int]  # (size, mtime_ns)


@dataclass(frozen=True)
class _Spec:
    path: Path
    depth: int  # how many directory levels below ``path`` to descend (0 = only its direct files)
    files_only: bool = False  # ignore directory entries (their mtime changes with unrelated activity)
    critical: bool = True
    exclude: tuple[Path, ...] = ()


@dataclass
class WriteReport:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    critical: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    def lines(self) -> list[str]:
        out = [
            f"{mark} {p}"
            for mark, items in (("+", self.added), ("~", self.modified), ("-", self.deleted))
            for p in items
        ]
        return out[:REPORT_MAX] + ([f"… and {len(out) - REPORT_MAX} more"] if len(out) > REPORT_MAX else [])


def _scan(spec: _Spec, out: dict[str, tuple[Meta, bool]], budget: list[int]) -> None:
    excluded = {_key(p) for p in spec.exclude}

    def walk(directory: Path, level: int) -> None:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return
        for entry in entries:
            if budget[0] <= 0:
                return
            try:
                if entry.is_symlink() or _key(entry.path) in excluded:
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                if is_dir:
                    if entry.name in _SKIP_DIRS and not spec.critical:
                        continue
                    if level < spec.depth:
                        walk(Path(entry.path), level + 1)
                    if spec.files_only:
                        continue
                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            budget[0] -= 1
            out[os.path.normcase(entry.path)] = ((stat.st_size, stat.st_mtime_ns), spec.critical)

    if spec.path.is_file():
        try:
            stat = spec.path.stat()
        except OSError:
            return
        out[os.path.normcase(str(spec.path))] = ((stat.st_size, stat.st_mtime_ns), spec.critical)
    elif spec.path.is_dir():
        walk(spec.path, 0)


def _git_toplevel(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").is_dir():
            return candidate
    return None


def watch_specs(run_dir: Path, project: Path, *, direct: bool) -> list[_Spec]:
    """Places outside ``run_dir`` that a task must not modify."""
    home = Path.home()
    specs = [_Spec(home / rel, depth=2, exclude=(run_dir,)) for rel in _HOME_WATCH]
    if direct:
        # Files next to the project; the project itself is the sanctioned write target.
        specs.append(_Spec(project.parent, depth=0, files_only=True, critical=False, exclude=(project,)))
    else:
        top = _git_toplevel(project)
        if top is not None:
            # Git hooks / config are shared with the worktree: tampering there runs code later.
            specs.append(_Spec(top / ".git" / "hooks", depth=0))
            specs.append(_Spec(top / ".git" / "config", depth=0))
            specs.append(_Spec(top / ".git" / "info", depth=1))
            # The user's own checkout stays untouched while the worktree is edited. Scanned last:
            # it is the only spec that can exhaust the entry budget.
            specs.append(_Spec(top, depth=6, files_only=True, critical=False))
    return specs


class WriteWatch:
    """Metadata snapshot of the watched places, comparable with a later ``check``."""

    def __init__(self, run_dir: Path, project: Path, *, direct: bool) -> None:
        self._specs = watch_specs(run_dir.resolve(), project.resolve(), direct=direct)
        self._before = self._collect()

    def _collect(self) -> dict[str, tuple[Meta, bool]]:
        out: dict[str, tuple[Meta, bool]] = {}
        budget = [WATCH_MAX_ENTRIES]
        for spec in self._specs:
            _scan(spec, out, budget)
        return out

    def check(self) -> WriteReport:
        after = self._collect()
        report = WriteReport()
        for path, (meta, critical) in after.items():
            old = self._before.get(path)
            if old is None:
                report.added.append(path)
            elif old[0] != meta:
                report.modified.append(path)
            else:
                continue
            if critical:
                report.critical.append(path)
        for path, (_meta, critical) in self._before.items():
            if path not in after:
                report.deleted.append(path)
                if critical:
                    report.critical.append(path)
        return report
