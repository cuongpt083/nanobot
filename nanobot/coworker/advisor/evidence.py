"""Harness-collected evidence for an advisor consult.

The transcript the advisor sees is elided (long tool arguments / results are cut), so a review of
"the plan I just saved" or "the diff" would otherwise rest on the executor's own word. This module
gathers ground truth the executor did not write: git state, the real diff of the files written
this run, the tail of recent verification commands, and (on request) files as they are on disk.
Everything is capped and best-effort — a failure here must never fail a consult.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from nanobot.coworker.transcript import (
    as_dict,
    as_list,
    content_text,
    tool_call_arguments,
    tool_call_name,
    tool_calls,
)

# file_write_staged proposes a write (it lands only on accept), but it is still a write the review
# gate and the evidence pack must see.
WRITE_TOOLS = frozenset({"write_file", "edit_file", "apply_patch", "file_write_staged"})
EXEC_TOOLS = frozenset({"exec", "exec_session"})

EVIDENCE_MAX_CHARS = 40_000
STATUS_MAX_CHARS = 3_000
DIFF_PER_FILE_MAX_CHARS = 8_000
MAX_DIFF_FILES = 12
NEW_FILE_HEAD_CHARS = 4_000
CHECK_TAIL_LINES = 30
MAX_CHECKS = 4
FILES_MAX = 5
FILE_MAX_CHARS = 20_000
FILES_TOTAL_MAX_CHARS = 60_000
GIT_TIMEOUT_S = 6

_CHECK_RE = re.compile(
    r"\b(pytest|ruff|mypy|basedpyright|tsc|vitest|eslint|jest|"
    r"bun\s+(?:run|x|test)|npm\s+(?:run|test)|pnpm\s+(?:run|test)|yarn\s+(?:run|test)|"
    r"cargo\s+(?:test|check|build|clippy)|go\s+(?:test|vet|build)|make\s+test)\b",
    re.IGNORECASE,
)
_EXIT_RE = re.compile(r"Exit code:\s*(-?\d+)", re.IGNORECASE)


def tool_call_paths(call: dict[str, Any]) -> list[str]:
    """File paths a write-tool call touches (``path`` or ``edits[].path``)."""
    if tool_call_name(call) not in WRITE_TOOLS:
        return []
    try:
        args = as_dict(json.loads(tool_call_arguments(call)))
    except ValueError:
        return []
    if args is None:
        return []
    paths: list[str] = []
    top = args.get("path")
    if isinstance(top, str) and top:
        paths.append(top)
    for raw in as_list(args.get("edits")) or []:
        edit = as_dict(raw)
        path = edit.get("path") if edit is not None else None
        if isinstance(path, str) and path:
            paths.append(path)
    return paths


def params_paths(tool: str, params: object) -> list[str]:
    """Same as :func:`tool_call_paths`, for already-parsed tool parameters."""
    args = as_dict(params)
    if args is None or tool not in WRITE_TOOLS:
        return []
    paths: list[str] = []
    top = args.get("path")
    if isinstance(top, str) and top:
        paths.append(top)
    for raw in as_list(args.get("edits")) or []:
        edit = as_dict(raw)
        path = edit.get("path") if edit is not None else None
        if isinstance(path, str) and path:
            paths.append(path)
    return paths


def written_paths(messages: Iterable[dict[str, Any]]) -> list[str]:
    """Distinct paths written in ``messages``, oldest first (a rewrite moves a path to the end)."""
    ordered: dict[str, None] = {}
    for message in messages:
        for call in tool_calls(message):
            for path in tool_call_paths(call):
                ordered.pop(path, None)
                ordered[path] = None
    return list(ordered)


def recent_checks(messages: list[dict[str, Any]], limit: int = MAX_CHECKS) -> list[tuple[str, str, int | None]]:
    """The last verification commands (test/lint/build) as ``(command, tail, exit_code)``."""
    results: dict[str, str] = {}
    for message in messages:
        if message.get("role") == "tool" and message.get("tool_call_id"):
            results[str(message["tool_call_id"])] = content_text(message.get("content"))
    found: list[tuple[str, str, int | None]] = []
    for message in messages:
        for call in tool_calls(message):
            if tool_call_name(call) not in EXEC_TOOLS:
                continue
            try:
                args = as_dict(json.loads(tool_call_arguments(call))) or {}
            except ValueError:
                continue
            command = str(args.get("command") or args.get("cmd") or "")
            if not _CHECK_RE.search(command):
                continue
            text = results.get(str(call.get("id") or ""), "")
            matches = _EXIT_RE.findall(text)
            exit_code = int(matches[-1]) if matches else None
            tail = "\n".join(text.strip().splitlines()[-CHECK_TAIL_LINES:])
            found.append((" ".join(command.split())[:200], tail, exit_code))
    return found[-limit:]


def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n…[{len(text) - limit} more chars]"


def git_summary(root: Path, *, max_chars: int = STATUS_MAX_CHARS) -> str:
    """``git status --short`` + ``git diff --stat``; empty when ``root`` is not a git work tree."""
    code, status = _git(root, "status", "--short")
    if code != 0:
        return ""
    _, stat = _git(root, "diff", "--stat", "HEAD")
    parts = [f"### git status --short\n{status.strip() or '(clean)'}"]
    if stat.strip():
        parts.append(f"### git diff --stat HEAD\n{stat.strip()}")
    return _clip("\n\n".join(parts), max_chars)


def _within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _resolve(root: Path, raw: str) -> Path | None:
    path = Path(raw)
    path = path if path.is_absolute() else root / path
    return path if _within(root, path) else None


def _read_text(path: Path, limit: int) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        return None
    return _clip(data.decode("utf-8", errors="replace"), limit)


def _written_diffs(root: Path, paths: list[str], budget: int) -> str:
    chunks: list[str] = []
    for raw in reversed(paths[-MAX_DIFF_FILES:]):  # newest first, so the budget favours recent work
        if budget <= 0:
            break
        path = _resolve(root, raw)
        if path is None:
            chunks.append(f"#### {raw}\n(outside the project scope — not inspected)")
            continue
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        code, tracked = _git(root, "ls-files", "--", rel)
        if code == 0 and tracked.strip():
            _, diff = _git(root, "diff", "--no-color", "-U2", "HEAD", "--", rel)
            body = diff.strip() or "(no uncommitted change: already committed or unchanged)"
            label = "diff vs HEAD"
        elif path.exists():
            head = _read_text(path, NEW_FILE_HEAD_CHARS)
            body = head if head is not None else "(binary or unreadable)"
            label = "new/untracked file, head"
        else:
            body, label = "(file no longer exists)", "missing"
        chunk = f"#### {rel} — {label}\n{_clip(body, DIFF_PER_FILE_MAX_CHARS)}"
        budget -= len(chunk)
        chunks.append(chunk)
    return "\n\n".join(chunks)


def _checks_section(checks: list[tuple[str, str, int | None]]) -> str:
    lines: list[str] = []
    for command, tail, code in checks:
        status = "exit code unknown" if code is None else f"exit code {code}"
        lines.append(f"- `{command}` → {status}")
        if tail:
            lines.append("  " + tail.replace("\n", "\n  "))
    return "\n".join(lines)


def read_requested_files(root: Path, requested: Iterable[str]) -> str:
    """Current on-disk content of ``requested`` project files (the executor's ``files`` argument)."""
    chunks: list[str] = []
    total = 0
    for raw in list(requested)[:FILES_MAX]:
        path = _resolve(root, raw)
        if path is None:
            chunks.append(f"#### {raw}\n(outside the project scope — not read)")
            continue
        text = _read_text(path, min(FILE_MAX_CHARS, max(0, FILES_TOTAL_MAX_CHARS - total)))
        if text is None:
            chunks.append(f"#### {raw}\n(missing, binary or unreadable)")
            continue
        total += len(text)
        chunks.append(f"#### {raw}\n{text}")
    return "\n\n".join(chunks)


PENDING_MAX = 5
PENDING_PREVIEW_CHARS = 800


def pending_proposals_section(root: Path) -> str:
    """Staged writes the user has not decided on. They are NOT on disk, so the advisor must not treat them as done."""
    from nanobot.coworker.staged.store import list_pending

    pending = list_pending(root)[:PENDING_MAX]
    if not pending:
        return ""
    blocks: list[str] = []
    for item in pending:
        preview = str(item.get("content", ""))[:PENDING_PREVIEW_CHARS]
        note = "changed on disk since it was proposed" if item.get("stale") else "not applied yet"
        blocks.append(
            f"#### {item.get('path')} ({note}; proposed by {item.get('by', 'unknown')})\n{preview}"
        )
    return "\n\n".join(blocks)


def collect_evidence_sync(
    messages: list[dict[str, Any]],
    root: Path | None,
    *,
    requested_files: Iterable[str] = (),
    run_messages: list[dict[str, Any]] | None = None,
    max_chars: int = EVIDENCE_MAX_CHARS,
) -> str:
    """The ``<harness_evidence>`` body, or ``""`` when there is nothing to add."""
    scope = run_messages if run_messages is not None else messages
    sections: list[str] = []
    if root is not None and root.is_dir():
        summary = git_summary(root)
        if summary:
            sections.append(summary)
        # Outside a git work tree the transcript only carries the first 600 characters of what a write
        # tool was given, so the file itself is the advisor's only view of what was produced.
        paths = written_paths(scope)
        if paths:
            diffs = _written_diffs(root, paths, max_chars // 2)
            if diffs:
                sections.append("### Files the executor wrote this run\n" + diffs)
        requested = list(requested_files)
        if requested:
            sections.append(
                "### Files the executor asked you to read (current content on disk)\n"
                + read_requested_files(root, requested)
            )
    if root is not None and root.is_dir():
        pending = pending_proposals_section(root)
        if pending:
            sections.append("### Proposed file changes awaiting the user's decision (not applied)\n" + pending)
    checks = _checks_section(recent_checks(scope))
    if checks:
        sections.append("### Recent verification commands (output tail as seen by the harness)\n" + checks)
    return _clip("\n\n".join(sections), max_chars) if sections else ""


async def collect_evidence(
    messages: list[dict[str, Any]],
    root: Path | None,
    **kwargs: Any,
) -> str:
    """Async wrapper: git subprocesses run off the event loop; any failure yields ``""``."""
    try:
        return await asyncio.to_thread(collect_evidence_sync, messages, root, **kwargs)
    except Exception:
        return ""


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    """Glob match against the full path and every trailing sub-path (``a/b/c.ts`` ~ ``b/c.ts``)."""
    norm = path.replace("\\", "/")
    parts = norm.split("/")
    candidates = {"/".join(parts[i:]) for i in range(len(parts))}
    return any(fnmatch.fnmatch(c, p) for p in patterns for c in candidates)
