"""Snapshot, change tracking and restore for ``direct`` coding tasks.

A ``direct`` task edits a plain (non-git) project directory in place. Before the harness runs
we record every file (and, when the tree is small enough, copy it), so afterwards we can report
what changed and undo it. Nothing here ever deletes the project directory itself: the only
things removed from the project are files the task *added*.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Directories that are build output / caches / tooling state: not tracked, not restored.
EXCLUDE_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next", ".nuxt", ".cache",
        ".coworker",
    }
)
EXCLUDE_FILES = frozenset({"task-contract.json"})
HASH_MAX_BYTES = 5 * 1024 * 1024
TEXT_DIFF_MAX_BYTES = 64 * 1024
MANIFEST_NAME = "manifest.json"
FILES_DIR = "files"


@dataclass(frozen=True)
class FileInfo:
    size: int
    mtime_ns: int
    sha256: str | None  # None for files larger than HASH_MAX_BYTES


@dataclass
class Manifest:
    files: dict[str, FileInfo] = field(default_factory=dict)
    copied: bool = False  # True when file contents were copied next to the manifest

    def to_json(self) -> str:
        return json.dumps(
            {
                "copied": self.copied,
                "files": {k: [v.size, v.mtime_ns, v.sha256] for k, v in self.files.items()},
            }
        )

    @classmethod
    def from_json(cls, text: str) -> Manifest:
        data = json.loads(text)
        files = {k: FileInfo(int(v[0]), int(v[1]), v[2]) for k, v in data.get("files", {}).items()}
        return cls(files=files, copied=bool(data.get("copied", False)))


@dataclass
class Changes:
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    def to_dict(self) -> dict[str, list[str]]:
        return {"added": self.added, "modified": self.modified, "deleted": self.deleted}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Changes:
        data = data or {}
        return cls(
            added=list(data.get("added", [])),
            modified=list(data.get("modified", [])),
            deleted=list(data.get("deleted", [])),
        )

    def summary(self) -> str:
        if not self:
            return "no changes"
        return f"{len(self.added)} added, {len(self.modified)} modified, {len(self.deleted)} deleted"


@dataclass
class RestoreResult:
    restored: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan(project: Path, previous: dict[str, FileInfo] | None = None) -> dict[str, FileInfo]:
    """Walk ``project`` (symlinks not followed, EXCLUDE_DIRS pruned) and describe every file.

    ``previous`` lets an unchanged file (same size and mtime) reuse its earlier hash.
    """
    result: dict[str, FileInfo] = {}
    for root, dirs, names in os.walk(project, followlinks=False):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in names:
            if name in EXCLUDE_FILES:
                continue
            full = Path(root) / name
            try:
                if full.is_symlink():
                    continue
                stat = full.stat()
            except OSError:
                continue
            rel = full.relative_to(project).as_posix()
            sha: str | None = None
            if stat.st_size <= HASH_MAX_BYTES:
                old = previous.get(rel) if previous else None
                if old is not None and old.size == stat.st_size and old.mtime_ns == stat.st_mtime_ns:
                    sha = old.sha256
                else:
                    try:
                        sha = _sha256(full)
                    except OSError:
                        continue
            result[rel] = FileInfo(stat.st_size, stat.st_mtime_ns, sha)
    return result


def take_snapshot(project: Path, dest: Path, *, max_mb: int) -> Manifest:
    """Record ``project`` into ``dest`` (manifest always; file copies when ≤ ``max_mb``)."""
    files = scan(project)
    total = sum(info.size for info in files.values())
    copied = total <= max_mb * 1024 * 1024
    dest.mkdir(parents=True, exist_ok=True)
    if copied:
        for rel in files:
            target = dest / FILES_DIR / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project / rel, target)
    manifest = Manifest(files=files, copied=copied)
    (dest / MANIFEST_NAME).write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def load_manifest(snapshot: Path) -> Manifest | None:
    try:
        return Manifest.from_json((snapshot / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None


def diff_manifest(before: Manifest, project: Path) -> Changes:
    """What the task added, modified and deleted relative to ``before``."""
    after = scan(project, previous=before.files)
    changes = Changes()
    for rel, info in after.items():
        old = before.files.get(rel)
        if old is None:
            changes.added.append(rel)
        elif old.size != info.size:
            changes.modified.append(rel)
        elif old.sha256 is not None and info.sha256 is not None:
            if old.sha256 != info.sha256:
                changes.modified.append(rel)
        elif old.mtime_ns != info.mtime_ns:
            changes.modified.append(rel)
    changes.deleted = [rel for rel in before.files if rel not in after]
    for items in (changes.added, changes.modified, changes.deleted):
        items.sort()
    return changes


def _read_text(path: Path) -> list[str] | None:
    try:
        if path.stat().st_size > TEXT_DIFF_MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (OSError, UnicodeDecodeError):
        return None


def text_diff(snapshot: Path, project: Path, changes: Changes, *, limit: int) -> str:
    """Unified diff for small text files (needs the copied snapshot); binary files are listed only."""
    chunks: list[str] = []
    notes: list[str] = []
    for rel in changes.modified:
        old = _read_text(snapshot / FILES_DIR / rel)
        new = _read_text(project / rel)
        if old is None or new is None:
            notes.append(f"M {rel} (binary or large file, no text diff)")
            continue
        chunks.append("".join(difflib.unified_diff(old, new, f"a/{rel}", f"b/{rel}")))
    for rel in changes.added:
        new = _read_text(project / rel)
        if new is None:
            notes.append(f"A {rel} (binary or large file)")
            continue
        chunks.append("".join(difflib.unified_diff([], new, "/dev/null", f"b/{rel}")))
    for rel in changes.deleted:
        old = _read_text(snapshot / FILES_DIR / rel)
        if old is None:
            notes.append(f"D {rel} (binary or large file)")
            continue
        chunks.append("".join(difflib.unified_diff(old, [], f"a/{rel}", "/dev/null")))
    text = "".join(chunks)
    if notes:
        text += ("\n" if text else "") + "\n".join(notes) + "\n"
    return text[:limit]


def restore(
    manifest: Manifest,
    snapshot: Path,
    project: Path,
    changes: Changes,
    *,
    since: float,
    force: bool = False,
) -> RestoreResult:
    """Undo ``changes``. Only listed files are touched; the project directory is never removed.

    A file modified after ``since`` (the moment the task finished) was probably edited by the
    user, so it is skipped unless ``force``.
    """
    result = RestoreResult()

    def touched_later(path: Path) -> bool:
        try:
            return path.stat().st_mtime > since
        except OSError:
            return False

    for rel in changes.added:
        target = project / rel
        if not target.exists():
            continue
        if not force and touched_later(target):
            result.skipped.append((rel, "changed after the task finished"))
            continue
        try:
            target.unlink()
            result.removed.append(rel)
        except OSError as exc:
            result.skipped.append((rel, str(exc)))

    for rel in [*changes.modified, *changes.deleted]:
        source = snapshot / FILES_DIR / rel
        target = project / rel
        if not manifest.copied or not source.exists():
            result.skipped.append((rel, "no copy of the original was kept"))
            continue
        if rel in changes.modified and not force and touched_later(target):
            result.skipped.append((rel, "changed after the task finished"))
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            result.restored.append(rel)
        except OSError as exc:
            result.skipped.append((rel, str(exc)))
    return result
