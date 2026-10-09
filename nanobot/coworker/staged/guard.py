"""Which writes an agent may make directly, and which must go through a reviewed proposal.

With staging on, the agent may write directly only inside ``.coworker/drafts/`` and only to a file no
editor tab has open. Everything else in the project is proposed with ``file_write_staged`` and reviewed.
"""

from __future__ import annotations

from pathlib import Path

from nanobot.coworker.staged.store import DRAFTS_DIR
from nanobot.coworker.staged.tools import STAGED_TOOL


def _relative(path: str, root: Path) -> str | None:
    candidate = Path(path)
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        return absolute.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return None  # outside the project: the write tool refuses it on its own


def blocked_paths(paths: list[str], root: Path, open_tabs: set[str]) -> list[str]:
    """The paths that must not be written directly. Paths outside the project are not listed here."""
    drafts = DRAFTS_DIR.as_posix()
    blocked: list[str] = []
    for raw in paths:
        rel = _relative(raw, root)
        if rel is None:
            continue
        in_drafts = rel == drafts or rel.startswith(drafts + "/")
        if not in_drafts or rel in open_tabs:
            blocked.append(rel)
    return blocked


def block_message(blocked: list[str]) -> str:
    listed = ", ".join(blocked[:5])
    return (
        f"Direct writes to {listed} are not allowed: this project keeps changes outside "
        f"{DRAFTS_DIR.as_posix()}/ (and files open in the editor) under review. Call "
        f"{STAGED_TOOL}(path, content, base_version) instead. Read the file first and pass its current "
        "version as base_version. The user reviews the proposal in the editor; do not retry the direct write."
    )
