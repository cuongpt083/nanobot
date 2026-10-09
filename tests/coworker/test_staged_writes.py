"""Staged writes (Phase 8): proposals are versioned, accepting re-checks the version, and the guard
only lets direct writes through inside the drafts folder when no editor tab has the file open."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from nanobot.coworker.staged import store
from nanobot.coworker.staged.guard import block_message, blocked_paths
from nanobot.webui.workspace_files import content_version


@pytest.fixture
def root(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "plan.md").write_bytes(b"v1 text\n")
    return project


def _scope(root: Path) -> SimpleNamespace:
    return SimpleNamespace(project_path=root)


def _propose(root: Path, **overrides) -> dict:
    args = dict(path="plan.md", content="v2 text\n", base_version=content_version(b"v1 text\n"),
                by="sales-writer", session_key="websocket:abc")
    args.update(overrides)
    return store.propose(root, **args)


def test_proposal_is_recorded_and_does_not_touch_the_file(root: Path) -> None:
    record = _propose(root)
    assert record["status"] == "pending" and record["path"] == "plan.md"
    assert (root / "plan.md").read_bytes() == b"v1 text\n"
    assert [c["id"] for c in store.list_pending(root)] == [record["id"]]


def test_an_existing_file_needs_its_version_and_a_stale_version_is_refused(root: Path) -> None:
    with pytest.raises(store.ProposalError) as exc:
        _propose(root, base_version=None)
    assert exc.value.status == 409 and "read it first" in exc.value.message
    with pytest.raises(store.ProposalError) as exc:
        _propose(root, base_version="sha256:0000")
    assert exc.value.status == 409 and exc.value.details["current_version"] == content_version(b"v1 text\n")


def test_a_new_file_is_created_with_no_base_version(root: Path) -> None:
    record = _propose(root, path="docs/new.md", base_version=None)
    assert record["base_version"] is None and record["path"] == "docs/new.md"


def test_a_newer_proposal_for_the_same_path_supersedes_the_older(root: Path) -> None:
    first = _propose(root)
    second = _propose(root, content="v3 text\n")
    pending = store.list_pending(root)
    assert [c["id"] for c in pending] == [second["id"]]
    superseded = next(r for r in store._read_records(root / store.STAGED_DIR) if r["id"] == first["id"])
    assert superseded["status"] == store.SUPERSEDED


def test_accepting_writes_the_file_and_closes_the_proposal(root: Path) -> None:
    record = _propose(root)
    result = store.resolve(root, record["id"], "accept", scope=_scope(root))
    assert result["status"] == "accepted" and result["version"] == content_version(b"v2 text\n")
    assert (root / "plan.md").read_bytes() == b"v2 text\n"
    assert store.list_pending(root) == []


def test_accepting_a_proposal_for_a_file_changed_since_is_refused_and_stays_pending(root: Path) -> None:
    record = _propose(root)
    (root / "plan.md").write_bytes(b"someone else\n")
    with pytest.raises(store.ProposalError) as exc:
        store.resolve(root, record["id"], "accept", scope=_scope(root))
    assert exc.value.status == 409
    assert (root / "plan.md").read_bytes() == b"someone else\n"
    pending = store.list_pending(root)
    assert len(pending) == 1 and pending[0]["stale"] is True


def test_rejecting_closes_the_proposal_without_writing(root: Path) -> None:
    record = _propose(root)
    result = store.resolve(root, record["id"], "reject", scope=_scope(root))
    assert result["status"] == "rejected"
    assert (root / "plan.md").read_bytes() == b"v1 text\n"
    with pytest.raises(store.ProposalError) as exc:
        store.resolve(root, record["id"], "accept", scope=_scope(root))
    assert exc.value.status == 404  # no longer pending


def test_a_proposal_outside_the_project_is_refused(root: Path, tmp_path: Path) -> None:
    with pytest.raises(store.ProposalError) as exc:
        _propose(root, path="../outside.md", base_version=None)
    assert exc.value.status in (403, 404)


def test_unknown_actions_are_refused(root: Path) -> None:
    record = _propose(root)
    with pytest.raises(store.ProposalError) as exc:
        store.resolve(root, record["id"], "merge", scope=_scope(root))
    assert exc.value.status == 400


# ---------- guard ----------

def test_direct_writes_are_allowed_only_in_drafts_with_no_tab_open(root: Path) -> None:
    drafts = ".coworker/drafts/notes.md"
    assert blocked_paths([drafts], root, set()) == []
    assert blocked_paths([drafts], root, {drafts}) == [drafts]  # open in a tab: reviewed
    assert blocked_paths(["plan.md"], root, set()) == ["plan.md"]  # outside drafts: reviewed


def test_paths_outside_the_project_are_left_to_the_write_tool(root: Path) -> None:
    assert blocked_paths(["/etc/hosts-not-here"], root, set()) == []


def test_the_block_message_names_the_proposal_tool() -> None:
    message = block_message(["plan.md"])
    assert "file_write_staged" in message and "base_version" in message


# ---------- hook wiring ----------

def _hook_with(monkeypatch: pytest.MonkeyPatch, root: Path, *, enabled: bool, open_tabs: list[str]):
    from nanobot.agent.hook import AgentTurnHookContext
    from nanobot.coworker.config import CoworkerConfig, StagingConfig
    from nanobot.coworker.hook import CoworkerHook
    from nanobot.coworker.runtime import COWORKER_META

    session = SimpleNamespace(metadata={COWORKER_META: {"open_tabs": open_tabs}})
    config = CoworkerConfig(staging=StagingConfig(enabled=enabled))
    monkeypatch.setattr("nanobot.coworker.hook.load_coworker_config", lambda: config)
    monkeypatch.setattr("nanobot.coworker.hook.get_session", lambda key: session)
    monkeypatch.setattr("nanobot.coworker.hook.project_root_for", lambda s: root)
    return CoworkerHook(AgentTurnHookContext(channel="cli", chat_id="direct", session_key="cli:direct"))


def _call(name: str, **arguments: object) -> SimpleNamespace:
    import json as _json

    return SimpleNamespace(name=name, arguments=_json.dumps(arguments), id="t1")


def _block(hook, call) -> str | None:
    return hook._staging_block(call, call_params(call))


def call_params(call) -> dict:
    import json as _json

    return _json.loads(call.arguments)


def test_guard_does_nothing_when_staging_is_off(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _hook_with(monkeypatch, root, enabled=False, open_tabs=[])
    assert _block(hook, _call("write_file", path="plan.md", content="x")) is None


def test_guard_refuses_a_direct_write_outside_drafts_and_says_how_to_propose(
    root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    hook = _hook_with(monkeypatch, root, enabled=True, open_tabs=[])
    blocked = _block(hook, _call("write_file", path="plan.md", content="x"))
    assert blocked is not None and "staging_required" in blocked and "file_write_staged" in blocked


def test_guard_lets_a_draft_through_unless_the_editor_has_it_open(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    draft = ".coworker/drafts/idea.md"
    free = _hook_with(monkeypatch, root, enabled=True, open_tabs=[])
    assert _block(free, _call("write_file", path=draft, content="x")) is None
    open_in_tab = _hook_with(monkeypatch, root, enabled=True, open_tabs=[draft])
    assert _block(open_in_tab, _call("write_file", path=draft, content="x")) is not None


def test_guard_never_blocks_the_proposal_tool_or_reads(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _hook_with(monkeypatch, root, enabled=True, open_tabs=["plan.md"])
    assert _block(hook, _call("file_write_staged", path="plan.md", content="x", base_version=None)) is None
    assert _block(hook, _call("read_file", path="plan.md")) is None


def test_guard_refuses_a_patch_whose_paths_cannot_be_read(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _hook_with(monkeypatch, root, enabled=True, open_tabs=[])
    blocked = _block(hook, _call("apply_patch", edits=[{"old": "a"}]))
    assert blocked is not None and "not readable" in blocked
