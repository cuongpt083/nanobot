"""fs.changed (Phase 8): which open files are watched, what counts as a change, and how it is delivered."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nanobot.webui.workspace_watch import Change, OpenFiles, deliver, event_body, poll


def test_only_project_relative_paths_are_watched(tmp_path: Path) -> None:
    registry = OpenFiles()
    registry.set("websocket:a", tmp_path, ["notes.md", "/etc/passwd", "../outside.md", "docs/plan.md"])
    [(key, root, paths)] = registry.items()
    assert key == "websocket:a" and root == tmp_path
    assert paths == frozenset({"notes.md", "docs/plan.md"})


def test_closing_all_tabs_stops_watching_the_session(tmp_path: Path) -> None:
    registry = OpenFiles()
    registry.set("websocket:a", tmp_path, ["notes.md"])
    registry.set("websocket:a", tmp_path, [])
    assert registry.items() == []


def test_the_first_poll_reports_nothing(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("one", encoding="utf-8")
    registry = OpenFiles()
    registry.set("websocket:a", tmp_path, ["notes.md"])
    changes, stamps = poll({}, registry)
    assert changes == []
    assert "notes.md" in stamps["websocket:a"]


def test_an_edit_on_disk_is_reported_once(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("one", encoding="utf-8")
    registry = OpenFiles()
    registry.set("websocket:a", tmp_path, ["notes.md"])
    _, stamps = poll({}, registry)

    target.write_text("two, longer", encoding="utf-8")
    changes, stamps = poll(stamps, registry)
    assert changes == [Change(session_key="websocket:a", path="notes.md")]

    changes_again, _ = poll(stamps, registry)
    assert changes_again == []


def test_a_deleted_or_created_file_is_reported(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("one", encoding="utf-8")
    registry = OpenFiles()
    registry.set("websocket:a", tmp_path, ["notes.md"])
    _, stamps = poll({}, registry)

    os.remove(target)
    changes, stamps = poll(stamps, registry)
    assert [c.path for c in changes] == ["notes.md"]

    target.write_text("back", encoding="utf-8")
    changes, _ = poll(stamps, registry)
    assert [c.path for c in changes] == ["notes.md"]


def test_an_unrelated_file_in_the_folder_is_not_reported(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("one", encoding="utf-8")
    (tmp_path / "other.md").write_text("other", encoding="utf-8")
    registry = OpenFiles()
    registry.set("websocket:a", tmp_path, ["notes.md"])
    _, stamps = poll({}, registry)
    (tmp_path / "other.md").write_text("changed other", encoding="utf-8")
    changes, _ = poll(stamps, registry)
    assert changes == []


def test_the_event_body_names_the_session_and_path() -> None:
    body = json.loads(event_body(Change(session_key="websocket:a", path="docs/plan.md")))
    assert body == {"event": "workspace_changed", "session_key": "websocket:a", "path": "docs/plan.md"}


@pytest.mark.asyncio
async def test_each_change_goes_to_every_connection() -> None:
    sent: list[tuple[str, str]] = []

    async def send(connection: str, frame: str) -> None:
        sent.append((connection, frame))

    count = await deliver(
        [Change(session_key="websocket:a", path="notes.md")],
        ["conn-1", "conn-2"],
        send,
    )
    assert count == 2
    assert [c for c, _ in sent] == ["conn-1", "conn-2"]
    assert all(json.loads(f)["event"] == "workspace_changed" for _, f in sent)
