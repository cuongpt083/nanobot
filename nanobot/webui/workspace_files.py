"""Workspace file browsing and editing for the WebUI editor pane (Phase 7.1).

Everything here is confined to the session's project root, even when the agent itself may read
more; a path that resolves outside it (including through a symlink) is refused. Writes are guarded
by a content version: a save states the version it was based on, and a save against a file that has
changed since is refused with 409 instead of silently overwriting the other edit.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nanobot.security.workspace_access import WorkspaceScope
from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path

EDIT_MAX_BYTES = 5 * 1024 * 1024
LIST_MAX_ENTRIES = 2000
_VERSION_PREFIX = "sha256:"


class WorkspaceFileError(ValueError):
    """A workspace file request that cannot be served; ``status`` is the HTTP status to report."""

    def __init__(self, status: int, message: str, **details: Any) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details


def content_version(data: bytes) -> str:
    return _VERSION_PREFIX + hashlib.sha256(data).hexdigest()[:16]


def _root(scope: WorkspaceScope) -> Path:
    return Path(scope.project_path).resolve()


def _resolve_inside(raw: str, root: Path, *, must_exist: bool) -> Path:
    if not raw or not raw.strip():
        raise WorkspaceFileError(400, "missing path")
    if len(raw) > 4096 or "\x00" in raw:
        raise WorkspaceFileError(400, "invalid path")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = resolve_allowed_path(
            candidate,
            workspace=root,
            allowed_root=root,
            strict=must_exist,
        )
    except FileNotFoundError as e:
        raise WorkspaceFileError(404, "file not found") from e
    except WorkspaceBoundaryError as e:
        raise WorkspaceFileError(403, "path is outside the project") from e
    except OSError as e:
        raise WorkspaceFileError(400, "invalid path") from e
    return resolved


def _check_name(name: str) -> str:
    if not name or name in {".", ".."} or "/" in name or "\\" in name or "\x00" in name:
        raise WorkspaceFileError(400, "invalid file name")
    if len(name) > 255:
        raise WorkspaceFileError(400, "file name is too long")
    return name


@dataclass(frozen=True)
class DirEntry:
    name: str
    kind: str  # "dir" | "file"
    size: int | None


def list_dir(raw_path: str | None, *, scope: WorkspaceScope) -> dict[str, Any]:
    root = _root(scope)
    directory = root if not raw_path else _resolve_inside(raw_path, root, must_exist=True)
    if not directory.is_dir():
        raise WorkspaceFileError(400, "not a directory")
    entries: list[DirEntry] = []
    truncated = False
    try:
        children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as e:
        raise WorkspaceFileError(500, "failed to list directory") from e
    for child in children:
        if len(entries) >= LIST_MAX_ENTRIES:
            truncated = True
            break
        try:
            # A link that points outside the project is not shown: opening it would be refused anyway.
            if not child.resolve().is_relative_to(root):
                continue
            if child.is_dir():
                entries.append(DirEntry(child.name, "dir", None))
            elif child.is_file():
                entries.append(DirEntry(child.name, "file", child.stat().st_size))
        except OSError:
            continue  # a broken link or a file that vanished during the listing
    return {
        "path": "" if directory == root else directory.relative_to(root).as_posix(),
        "entries": [{"name": e.name, "kind": e.kind, "size": e.size} for e in entries],
        "truncated": truncated,
    }


def read_file(raw_path: str | None, *, scope: WorkspaceScope) -> dict[str, Any]:
    root = _root(scope)
    target = _resolve_inside(raw_path or "", root, must_exist=True)
    if not target.is_file():
        raise WorkspaceFileError(404, "file not found")
    size = target.stat().st_size
    if size > EDIT_MAX_BYTES:
        raise WorkspaceFileError(413, "file is too large to edit (maximum 5 MiB)", size=size)
    data = target.read_bytes()
    if b"\0" in data[:4096]:
        raise WorkspaceFileError(415, "binary files cannot be edited")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise WorkspaceFileError(415, "only UTF-8 text files can be edited") from e
    return {
        "path": target.relative_to(root).as_posix(),
        "content": text,
        "version": content_version(data),
        "size": size,
    }


def _current_version(target: Path) -> str | None:
    if not target.exists():
        return None
    return content_version(target.read_bytes())


def write_file(
    raw_path: str | None,
    content: Any,
    *,
    base_version: Any,
    scope: WorkspaceScope,
) -> dict[str, Any]:
    """Save ``content``. ``base_version`` is the version the editor loaded; ``None`` means "create"."""
    if not isinstance(content, str):
        raise WorkspaceFileError(400, "content must be a string")
    data = content.encode("utf-8")
    if len(data) > EDIT_MAX_BYTES:
        raise WorkspaceFileError(413, "content is too large to save (maximum 5 MiB)")
    if base_version is not None and not isinstance(base_version, str):
        raise WorkspaceFileError(400, "base_version must be a string or null")
    root = _root(scope)
    target = _resolve_inside(raw_path or "", root, must_exist=False)
    if target.is_dir():
        raise WorkspaceFileError(400, "path is a directory")

    current = _current_version(target)
    if current != base_version:
        raise WorkspaceFileError(
            409,
            "file changed since it was opened",
            current_version=current,
        )

    # _resolve_inside already confined the target; creating its parents stays inside the project too.
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except OSError as e:
        temp.unlink(missing_ok=True)
        raise WorkspaceFileError(500, "failed to save file") from e
    return {
        "path": target.relative_to(root).as_posix(),
        "version": content_version(data),
        "size": len(data),
    }


def rename_file(raw_path: str | None, new_name: Any, *, scope: WorkspaceScope) -> dict[str, Any]:
    if not isinstance(new_name, str):
        raise WorkspaceFileError(400, "new name must be a string")
    name = _check_name(new_name.strip())
    root = _root(scope)
    source = _resolve_inside(raw_path or "", root, must_exist=True)
    target = source.parent / name
    if target.exists():
        raise WorkspaceFileError(409, "a file with that name already exists")
    _resolve_inside(target.relative_to(root).as_posix(), root, must_exist=False)
    try:
        source.rename(target)
    except OSError as e:
        raise WorkspaceFileError(500, "failed to rename file") from e
    return {"path": target.relative_to(root).as_posix()}


def delete_file(raw_path: str | None, *, base_version: Any, scope: WorkspaceScope) -> dict[str, Any]:
    root = _root(scope)
    target = _resolve_inside(raw_path or "", root, must_exist=True)
    if not target.is_file():
        raise WorkspaceFileError(400, "only files can be deleted")
    if base_version is not None:
        current = content_version(target.read_bytes())
        if current != base_version:
            raise WorkspaceFileError(409, "file changed since it was opened", current_version=current)
    try:
        target.unlink()
    except OSError as e:
        raise WorkspaceFileError(500, "failed to delete file") from e
    return {"path": target.relative_to(root).as_posix(), "deleted": True}
