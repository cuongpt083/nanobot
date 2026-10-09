"""Staged file changes: an agent proposes a write, the user reviews it in the editor (Phase 8).

A proposal is a JSON record under ``<project>/.coworker/staged/``. It remembers the content version of
the target when the agent proposed the change. Accepting re-checks that version, so a file that changed
in the meantime is never overwritten by a stale proposal; the agent is told to read the file again.
At most one pending proposal exists per path: a newer one supersedes the older.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, cast

from nanobot.security.workspace_policy import WorkspaceBoundaryError, resolve_allowed_path
from nanobot.webui.workspace_files import WorkspaceFileError, content_version, write_file

STAGED_DIR = Path(".coworker") / "staged"
DRAFTS_DIR = Path(".coworker") / "drafts"
PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"
SUPERSEDED = "superseded"


class ProposalError(ValueError):
    """A proposal the agent must correct; ``status`` is 400 invalid, 404 unknown, 409 stale, 403 outside."""

    def __init__(self, status: int, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}


def _staged_dir(root: Path) -> Path:
    return root / STAGED_DIR


def _resolve_in_project(raw: str, root: Path, *, must_exist: bool) -> Path:
    if not raw or not raw.strip():
        raise ProposalError(400, "missing path", {})
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return resolve_allowed_path(candidate, workspace=root, allowed_root=root, strict=must_exist)
    except FileNotFoundError as e:
        raise ProposalError(404, "file not found", {}) from e
    except WorkspaceBoundaryError as e:
        raise ProposalError(403, "path is outside the project", {}) from e
    except OSError as e:
        raise ProposalError(400, "invalid path", {}) from e


def _current_version(target: Path) -> str | None:
    return content_version(target.read_bytes()) if target.is_file() else None


def _write_record(directory: Path, record: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{record['id']}.json"
    temp = directory / f".{record['id']}.{uuid.uuid4().hex}.tmp"
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, target)


def _read_records(directory: Path) -> list[dict[str, Any]]:
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for item in directory.glob("*.json"):
        try:
            data: object = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # a torn record from a killed process; ignore rather than fail the list
        if isinstance(data, dict):
            record = cast("dict[str, Any]", data)
            if isinstance(record.get("id"), str):
                records.append(record)
    return records


def propose(
    root: Path,
    *,
    path: str,
    content: Any,
    base_version: Any,
    by: str,
    session_key: str | None,
) -> dict[str, Any]:
    if not isinstance(content, str):
        raise ProposalError(400, "content must be a string", {})
    data = content.encode("utf-8")
    if len(data) > 5 * 1024 * 1024:
        raise ProposalError(413, "content is too large to propose (maximum 5 MiB)", {})
    if base_version is not None and not isinstance(base_version, str):
        raise ProposalError(400, "base_version must be a string or null", {})

    target = _resolve_in_project(path, root, must_exist=False)
    if target.is_dir():
        raise ProposalError(400, "path is a directory", {})
    rel = target.relative_to(root).as_posix()
    current = _current_version(target)

    if current is not None and base_version is None:
        raise ProposalError(
            409,
            "the file exists: read it first and pass its version as base_version",
            {"current_version": current},
        )
    if current != base_version:
        raise ProposalError(
            409,
            "the file changed since you read it: read it again, then propose again",
            {"current_version": current},
        )

    directory = _staged_dir(root)
    for existing in _read_records(directory):
        if existing.get("status") == PENDING and existing.get("path") == rel:
            existing["status"] = SUPERSEDED
            _write_record(directory, existing)

    record = {
        "id": uuid.uuid4().hex[:12],
        "path": rel,
        "content": content,
        "base_version": base_version,
        "proposed_version": content_version(data),
        "by": by,
        "session_key": session_key,
        "created_at": int(time.time() * 1000),
        "status": PENDING,
    }
    _write_record(directory, record)
    return record


def list_pending(root: Path) -> list[dict[str, Any]]:
    """Pending proposals, newest first, each with whether the file has changed since it was proposed."""
    out: list[dict[str, Any]] = []
    for record in _read_records(_staged_dir(root)):
        if record.get("status") != PENDING:
            continue
        target = root / str(record.get("path", ""))
        try:
            current = _current_version(target) if target.exists() else None
        except OSError:
            current = None
        out.append({
            **record,
            "current_version": current,
            "stale": current != record.get("base_version"),
        })
    out.sort(key=lambda r: int(r.get("created_at") or 0), reverse=True)
    return out


def resolve(root: Path, change_id: str, action: str, *, scope: Any) -> dict[str, Any]:
    """Accept (write the proposed content) or reject a pending proposal."""
    if action not in {"accept", "reject"}:
        raise ProposalError(400, "action must be accept or reject", {})
    directory = _staged_dir(root)
    record = next((r for r in _read_records(directory) if r.get("id") == change_id), None)
    if record is None or record.get("status") != PENDING:
        raise ProposalError(404, "no pending change with that id", {})

    if action == "reject":
        record["status"] = REJECTED
        _write_record(directory, record)
        return {"id": change_id, "status": REJECTED, "path": record["path"]}

    try:
        saved = write_file(
            record["path"],
            record["content"],
            base_version=record.get("base_version"),
            scope=scope,
        )
    except WorkspaceFileError as e:
        if e.status == 409:
            raise ProposalError(409, "the file changed since the agent read it; the proposal is stale",
                                {"current_version": e.details.get("current_version")}) from e
        raise ProposalError(e.status, e.message, {}) from e
    record["status"] = ACCEPTED
    _write_record(directory, record)
    return {"id": change_id, "status": ACCEPTED, "path": record["path"], "version": saved["version"]}
