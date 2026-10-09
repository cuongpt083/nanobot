"""Workspace file browse/edit: path confinement, version-guarded saves, rename and delete."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.webui import workspace_files as wf
from nanobot.webui.workspace_files import WorkspaceFileError


@pytest.fixture
def project(tmp_path: Path) -> SimpleNamespace:
    root = tmp_path / "proj"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "plan.md").write_bytes("# Plan\n".encode("utf-8"))
    (root / "notes.txt").write_bytes("hello\n".encode("utf-8"))
    (root / "image.bin").write_bytes(b"\x89PNG\x00\x00binary")
    # Only ``project_path`` is read by the module; the rest of WorkspaceScope is not needed here.
    return SimpleNamespace(project_path=root)


def _status(exc_info: pytest.ExceptionInfo[WorkspaceFileError]) -> int:
    return exc_info.value.status


def test_list_puts_directories_first_and_reports_sizes(project) -> None:
    listing = wf.list_dir(None, scope=project)
    assert listing["path"] == ""
    assert [(e["name"], e["kind"]) for e in listing["entries"]] == [
        ("docs", "dir"),
        ("image.bin", "file"),
        ("notes.txt", "file"),
    ]
    assert listing["entries"][2]["size"] == len("hello\n")
    sub = wf.list_dir("docs", scope=project)
    assert sub["path"] == "docs" and sub["entries"][0]["name"] == "plan.md"


def test_list_hides_links_that_leave_the_project(project, tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_bytes("nope".encode("utf-8"))
    try:
        os.symlink(outside, project.project_path / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this platform")
    names = [e["name"] for e in wf.list_dir(None, scope=project)["entries"]]
    assert "link.txt" not in names


def test_read_returns_content_and_a_version(project) -> None:
    payload = wf.read_file("notes.txt", scope=project)
    assert payload["content"] == "hello\n"
    assert payload["version"] == wf.content_version(b"hello\n")
    assert payload["path"] == "notes.txt"


@pytest.mark.parametrize("raw", ["../outside.txt", "/etc/passwd-not-here", "docs/../../escape"])
def test_paths_outside_the_project_are_refused(project, tmp_path: Path, raw: str) -> None:
    (tmp_path / "outside.txt").write_bytes("x".encode("utf-8"))
    with pytest.raises(WorkspaceFileError) as exc:
        wf.read_file(raw, scope=project)
    assert _status(exc) in (403, 404)


def test_binary_and_missing_files_are_reported_with_their_own_status(project) -> None:
    with pytest.raises(WorkspaceFileError) as exc:
        wf.read_file("image.bin", scope=project)
    assert _status(exc) == 415
    with pytest.raises(WorkspaceFileError) as exc:
        wf.read_file("missing.txt", scope=project)
    assert _status(exc) == 404


def test_read_refuses_files_over_the_edit_cap(project, monkeypatch) -> None:
    monkeypatch.setattr(wf, "EDIT_MAX_BYTES", 4)
    with pytest.raises(WorkspaceFileError) as exc:
        wf.read_file("notes.txt", scope=project)
    assert _status(exc) == 413


def test_save_with_the_loaded_version_succeeds_and_leaves_no_temp_file(project) -> None:
    loaded = wf.read_file("notes.txt", scope=project)
    saved = wf.write_file("notes.txt", "hello world\n", base_version=loaded["version"], scope=project)
    assert saved["version"] == wf.content_version(b"hello world\n")
    assert (project.project_path / "notes.txt").read_text(encoding="utf-8") == "hello world\n"
    leftovers = [p.name for p in project.project_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_save_against_a_changed_file_is_refused_and_keeps_the_other_edit(project) -> None:
    loaded = wf.read_file("notes.txt", scope=project)
    (project.project_path / "notes.txt").write_bytes("someone else\n".encode("utf-8"))
    with pytest.raises(WorkspaceFileError) as exc:
        wf.write_file("notes.txt", "mine\n", base_version=loaded["version"], scope=project)
    assert _status(exc) == 409
    assert exc.value.details["current_version"] == wf.content_version(b"someone else\n")
    assert (project.project_path / "notes.txt").read_text(encoding="utf-8") == "someone else\n"


def test_create_needs_base_version_none_and_refuses_to_clobber(project) -> None:
    created = wf.write_file("docs/new.md", "# New\n", base_version=None, scope=project)
    assert created["path"] == "docs/new.md"
    with pytest.raises(WorkspaceFileError) as exc:
        wf.write_file("docs/new.md", "again\n", base_version=None, scope=project)
    assert _status(exc) == 409


def test_save_validates_the_payload(project) -> None:
    with pytest.raises(WorkspaceFileError) as exc:
        wf.write_file("notes.txt", 42, base_version=None, scope=project)
    assert _status(exc) == 400
    with pytest.raises(WorkspaceFileError) as exc:
        wf.write_file("notes.txt", "x" * (wf.EDIT_MAX_BYTES + 1), base_version=None, scope=project)
    assert _status(exc) == 413


def test_rename_stays_in_the_same_folder_and_refuses_existing_names(project) -> None:
    renamed = wf.rename_file("notes.txt", "todo.txt", scope=project)
    assert renamed["path"] == "todo.txt"
    assert (project.project_path / "todo.txt").exists() and not (project.project_path / "notes.txt").exists()
    with pytest.raises(WorkspaceFileError) as exc:
        wf.rename_file("todo.txt", "image.bin", scope=project)
    assert _status(exc) == 409
    for bad in ("../escape.txt", "a/b.txt", "..", ""):
        with pytest.raises(WorkspaceFileError) as exc:
            wf.rename_file("todo.txt", bad, scope=project)
        assert _status(exc) == 400


def test_delete_removes_a_file_and_is_guarded_by_version(project) -> None:
    loaded = wf.read_file("notes.txt", scope=project)
    (project.project_path / "notes.txt").write_bytes("changed\n".encode("utf-8"))
    with pytest.raises(WorkspaceFileError) as exc:
        wf.delete_file("notes.txt", base_version=loaded["version"], scope=project)
    assert _status(exc) == 409
    assert wf.delete_file("notes.txt", base_version=None, scope=project)["deleted"] is True
    assert not (project.project_path / "notes.txt").exists()


def test_directories_cannot_be_deleted_or_saved_over(project) -> None:
    with pytest.raises(WorkspaceFileError) as exc:
        wf.delete_file("docs", base_version=None, scope=project)
    assert _status(exc) == 400
    with pytest.raises(WorkspaceFileError) as exc:
        wf.write_file("docs", "x", base_version=None, scope=project)
    assert _status(exc) == 400
