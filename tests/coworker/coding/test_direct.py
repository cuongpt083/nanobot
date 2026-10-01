"""Direct mode: non-git projects are edited in place, with a snapshot to diff and undo."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.coworker.coding import direct
from nanobot.coworker.coding.project import (
    DirectConfirmationError,
    ProjectError,
    direct_allowed,
    grant_direct,
)
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.tasks import CodingTask
from nanobot.coworker.coding.workspace import WorkspaceManager
from nanobot.coworker.config import (
    CodingAgentConfig,
    CoworkerConfig,
    PiBackendConfig,
    RepoConfig,
)

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")
PNG_A = bytes([0x89, 0x50, 0x4E, 0x47, 0x00, 0x01]) * 10
PNG_B = bytes([0x89, 0x50, 0x4E, 0x47, 0x00, 0x02]) * 10


def _tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "notes.md").write_text("# notes\nline\n", encoding="utf-8")
    (root / "slides").mkdir()
    (root / "slides" / "deck.txt").write_text("slide 1\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
    return root


def _bump(path: Path, seconds: float = 5.0) -> None:
    """Push mtime forward so same-size edits are seen even on coarse filesystems."""
    stat = path.stat()
    os.utime(path, (stat.st_atime, stat.st_mtime + seconds))


# --- snapshot / manifest --------------------------------------------------------------


def test_snapshot_copies_small_trees_and_skips_excluded_dirs(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    snap = tmp_path / "snap"
    manifest = direct.take_snapshot(project, snap, max_mb=10)
    assert manifest.copied
    assert set(manifest.files) == {"notes.md", "slides/deck.txt"}  # node_modules ignored
    assert (snap / "files" / "slides" / "deck.txt").read_text(encoding="utf-8") == "slide 1\n"
    assert direct.load_manifest(snap) is not None


def test_snapshot_over_the_limit_keeps_only_a_manifest(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    (project / "big.bin").write_bytes(b"0" * (2 * 1024 * 1024))
    snap = tmp_path / "snap"
    manifest = direct.take_snapshot(project, snap, max_mb=1)
    assert not manifest.copied
    assert "big.bin" in manifest.files
    assert not (snap / "files").exists()
    assert manifest.files["big.bin"].sha256 is not None  # up to 5 MB is still hashed


def test_manifest_json_roundtrip(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    manifest = direct.take_snapshot(project, tmp_path / "snap", max_mb=10)
    again = direct.Manifest.from_json(manifest.to_json())
    assert again.files == manifest.files
    assert again.copied is True


# --- change detection -----------------------------------------------------------------


def test_diff_reports_added_modified_deleted(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    manifest = direct.take_snapshot(project, tmp_path / "snap", max_mb=10)
    (project / "notes.md").write_text("# notes\nline CHANGED\n", encoding="utf-8")
    (project / "slides" / "deck.txt").unlink()
    (project / "new.txt").write_text("hello", encoding="utf-8")
    (project / "node_modules" / "more.js").write_text("y", encoding="utf-8")  # ignored

    changes = direct.diff_manifest(manifest, project)
    assert changes.added == ["new.txt"]
    assert changes.modified == ["notes.md"]
    assert changes.deleted == ["slides/deck.txt"]
    assert changes.summary() == "1 added, 1 modified, 1 deleted"


def test_same_size_edit_is_detected_and_touch_alone_is_not_a_change(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    manifest = direct.take_snapshot(project, tmp_path / "snap", max_mb=10)
    (project / "notes.md").write_text("# notes\nlinX\n", encoding="utf-8")  # same length
    _bump(project / "notes.md")
    _bump(project / "slides" / "deck.txt")  # new mtime, same content
    changes = direct.diff_manifest(manifest, project)
    assert changes.modified == ["notes.md"]


def test_unchanged_tree_has_no_changes(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    manifest = direct.take_snapshot(project, tmp_path / "snap", max_mb=10)
    assert not direct.diff_manifest(manifest, project)


def test_text_diff_is_capped_and_lists_binary_files(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    (project / "logo.png").write_bytes(PNG_A)
    snap = tmp_path / "snap"
    manifest = direct.take_snapshot(project, snap, max_mb=10)
    (project / "notes.md").write_text("# notes\nchanged\n", encoding="utf-8")
    (project / "logo.png").write_bytes(PNG_B)
    changes = direct.diff_manifest(manifest, project)
    text = direct.text_diff(snap, project, changes, limit=10_000)
    assert "+changed" in text and "-line" in text
    assert "logo.png (binary or large file" in text
    assert len(direct.text_diff(snap, project, changes, limit=20)) == 20


# --- restore --------------------------------------------------------------------------


def test_restore_undoes_only_the_listed_changes(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    snap = tmp_path / "snap"
    manifest = direct.take_snapshot(project, snap, max_mb=10)
    (project / "notes.md").write_text("task edit\n", encoding="utf-8")
    (project / "slides" / "deck.txt").unlink()
    (project / "added.txt").write_text("new", encoding="utf-8")
    changes = direct.diff_manifest(manifest, project)
    finished = time.time() + 60  # everything above happened "before the task finished"

    result = direct.restore(manifest, snap, project, changes, since=finished)
    assert sorted(result.restored) == ["notes.md", "slides/deck.txt"]
    assert result.removed == ["added.txt"]
    assert (project / "notes.md").read_text(encoding="utf-8") == "# notes\nline\n"
    assert (project / "slides" / "deck.txt").exists()
    assert not (project / "added.txt").exists()
    assert project.exists()


def test_restore_skips_files_the_user_edited_after_the_task(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    snap = tmp_path / "snap"
    manifest = direct.take_snapshot(project, snap, max_mb=10)
    (project / "notes.md").write_text("task edit\n", encoding="utf-8")
    changes = direct.diff_manifest(manifest, project)
    finished = time.time() - 60  # task "finished" a minute ago; the file is newer
    result = direct.restore(manifest, snap, project, changes, since=finished)
    assert result.restored == []
    assert result.skipped == [("notes.md", "changed after the task finished")]
    assert (project / "notes.md").read_text(encoding="utf-8") == "task edit\n"

    forced = direct.restore(manifest, snap, project, changes, since=finished, force=True)
    assert forced.restored == ["notes.md"]


def test_restore_without_copies_removes_added_files_but_cannot_restore_others(
    tmp_path: Path,
) -> None:
    project = _tree(tmp_path / "docs")
    (project / "big.bin").write_bytes(b"0" * (2 * 1024 * 1024))
    snap = tmp_path / "snap"
    manifest = direct.take_snapshot(project, snap, max_mb=1)
    (project / "notes.md").write_text("task edit\n", encoding="utf-8")
    (project / "added.txt").write_text("a", encoding="utf-8")
    changes = direct.diff_manifest(manifest, project)
    result = direct.restore(manifest, snap, project, changes, since=time.time() + 60)
    assert result.removed == ["added.txt"]
    assert result.skipped == [("notes.md", "no copy of the original was kept")]


# --- never deleting the project --------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_and_prune_never_touch_the_project(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    cfg = CodingAgentConfig(enabled=True, repos=[])
    mgr = WorkspaceManager(cfg, tmp_path / "ws")
    old = mgr.worktree_base / "ct-old" / "snapshot"
    old.mkdir(parents=True)
    os.utime(old.parent, (1, 1))

    await mgr.cleanup(repo=RepoConfig(path=str(project)), task_id="ct-old", delete_branch=True)
    await mgr.prune_expired(1)
    assert (project / "notes.md").exists()
    assert (project / "slides" / "deck.txt").exists()
    assert not old.parent.exists()  # only the snapshot directory goes


# --- admission: consent, policy, lock -----------------------------------------------------


def _runner(tmp_path: Path, **coding: Any) -> CodingRunner:
    cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="pi",
            repos=[],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT],
                allow_unsandboxed=True,
                pass_env=["FAKE_PI_SCENARIO"],
            ),
            **coding,
        )
    )
    return CodingRunner(cfg, tmp_path / "ws")


def _session(project: Path) -> SimpleNamespace:
    return SimpleNamespace(
        metadata={"workspace_scope": {"project_path": str(project), "access_mode": "restricted"}}
    )


async def _admit(runner: CodingRunner, session: SimpleNamespace, key: str = "s1") -> Any:
    with patch("nanobot.coworker.coding.runner._lookup_session", return_value=session):
        return await runner.admit_async(brief="b", session_key=key, channel="c", chat_id="u")


@pytest.mark.asyncio
async def test_ask_policy_needs_the_users_consent_for_a_non_git_project(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    runner = _runner(tmp_path)
    session = _session(project)

    with pytest.raises(DirectConfirmationError) as info:
        await _admit(runner, session)
    assert info.value.path == project.resolve()
    assert runner.registry.count_active() == 0  # the failed admission released its slot

    grant_direct(session, project)
    assert direct_allowed(session, project)
    task, _backend, _repo = await _admit(runner, session)
    assert task.mode == "direct"
    assert task.workdir == str(project.resolve())
    assert task.branch == "" and task.base == ""
    assert task.run_dir == project.resolve()


@pytest.mark.asyncio
async def test_consent_is_per_project(tmp_path: Path) -> None:
    a = _tree(tmp_path / "a")
    b = _tree(tmp_path / "b")
    session = _session(b)
    grant_direct(session, a)
    assert not direct_allowed(session, b)
    assert not direct_allowed(None, a)
    with pytest.raises(DirectConfirmationError):
        await _admit(_runner(tmp_path), session)


@pytest.mark.asyncio
async def test_direct_policy_skips_the_question_and_refuse_blocks(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    task, _b, _r = await _admit(_runner(tmp_path, non_git="direct"), _session(project))
    assert task.mode == "direct"

    with pytest.raises(ProjectError, match="refuse"):
        await _admit(_runner(tmp_path / "other", non_git="refuse"), _session(project), "s2")


@pytest.mark.asyncio
async def test_only_one_direct_task_per_directory(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    runner = _runner(
        tmp_path, non_git="direct", max_concurrent_per_session=5, max_concurrent_total=5
    )
    session = _session(project)
    await _admit(runner, session, "s1")
    with pytest.raises(ProjectError, match="already editing"):
        await _admit(runner, session, "s2")
    other = _tree(tmp_path / "docs2")
    task, _b, _r = await _admit(runner, _session(other), "s3")
    assert task.mode == "direct"


@pytest.mark.asyncio
async def test_git_repository_without_commits_is_treated_as_direct(tmp_path: Path) -> None:
    project = tmp_path / "fresh"
    project.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=project, check=True, capture_output=True)
    task, _b, _r = await _admit(_runner(tmp_path, non_git="direct"), _session(project))
    assert task.mode == "direct"


def test_old_task_files_load_as_worktree_tasks() -> None:
    legacy = {
        "id": "ct-1", "backend": "pi", "session_key": "s", "channel": "c", "chat_id": "u",
        "repo": "/r", "base": "HEAD", "branch": "b", "worktree": "/w", "brief": "x",
    }
    task = CodingTask.from_dict(legacy)
    assert task.mode == "worktree" and task.workdir == "" and task.changes == {}


# --- end to end with the fake harness ----------------------------------------------------


@pytest.mark.asyncio
async def test_direct_task_edits_in_place_and_reports_changes(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    runner = _runner(tmp_path, non_git="direct")
    task, backend, repo = await _admit(runner, _session(project))

    with patch("nanobot.coworker.coding.runner.inject_turn", new_callable=AsyncMock) as inject:
        with patch.dict(os.environ, {"FAKE_PI_SCENARIO": "write_file:made.txt:by the harness"}):
            message = await runner.execute_task(task, backend, repo, wait=False)

    assert task.status == "succeeded"
    assert (project / "made.txt").read_text(encoding="utf-8").startswith("by the harness")
    assert task.changes["added"] == ["made.txt"]
    assert task.diffstat == "1 added, 0 modified, 0 deleted"
    assert task.snapshot and Path(task.snapshot, "manifest.json").exists()
    assert task.finished_at > 0
    assert "edited in place" in message and "+ made.txt" in message
    assert "/code merge" not in message and "/code discard" in message
    inject.assert_awaited_once()
    assert runner.registry.count_active_direct(project) == 0  # lock released


@pytest.mark.asyncio
async def test_snapshot_failure_marks_the_task_and_still_reports(tmp_path: Path) -> None:
    project = _tree(tmp_path / "docs")
    runner = _runner(tmp_path, non_git="direct")
    task, backend, repo = await _admit(runner, _session(project))
    with (
        patch("nanobot.coworker.coding.runner.inject_turn", new_callable=AsyncMock) as inject,
        patch(
            "nanobot.coworker.coding.runner.direct_mod.take_snapshot",
            side_effect=OSError("disk full"),
        ),
    ):
        message = await runner.execute_task(task, backend, repo, wait=False)
    assert task.status == "error"
    assert "Setup failed: disk full" in (task.error or "")
    assert "disk full" in message
    inject.assert_awaited_once()
    assert runner.registry.count_active_direct(project) == 0
