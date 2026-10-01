"""`/code init`: turning a plain folder into a git repository only after the user has seen the files."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nanobot.command.router import CommandContext
from nanobot.coworker import session_api
from nanobot.coworker.coding import init_repo
from nanobot.coworker.coding.commands import cmd_code
from nanobot.coworker.coding.init_repo import InitError, plan_init, run_init
from nanobot.coworker.coding.project import init_preview, pending_direct, set_pending_direct
from nanobot.coworker.coding.runner import CodingRunner
from nanobot.coworker.coding.workspace import inspect_project
from nanobot.coworker.config import (
    CodingAgentConfig,
    CoworkerConfig,
    PiBackendConfig,
    set_coworker_config_override,
)
from nanobot.coworker.session_api import SessionApiError
from nanobot.coworker.status import coworker_session_status
from nanobot.session.manager import Session

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """No user/global git config: the commit must work with nanobot's fallback identity."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    set_coworker_config_override(CoworkerConfig())
    yield
    set_coworker_config_override(None)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _folder(tmp_path: Path, name: str = "docs") -> Path:
    root = tmp_path / name
    (root / "slides").mkdir(parents=True)
    (root / "notes.md").write_text("# notes\n", encoding="utf-8")
    (root / "slides" / "deck.txt").write_text("slide\n", encoding="utf-8")
    (root / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
    return root


def _tracked(root: Path) -> set[str]:
    return {p for p in _git(root, "ls-files").splitlines() if p}


# --- the preview never touches the folder ------------------------------------------------


def test_plan_lists_files_without_secrets_or_caches_and_changes_nothing(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    before = sorted(p.name for p in root.iterdir())
    plan = plan_init(root)
    assert plan.files == ["notes.md", "slides/deck.txt"]
    assert ".env" in plan.skipped_sensitive
    assert plan.gitignore_text is not None and "node_modules/" in plan.gitignore_text
    assert plan.digest
    assert sorted(p.name for p in root.iterdir()) == before  # no .git, no .gitignore
    assert plan_init(root).digest == plan.digest  # stable for an unchanged folder


def test_plan_digest_changes_when_the_folder_changes(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    first = plan_init(root).digest
    (root / "extra.md").write_text("new", encoding="utf-8")
    assert plan_init(root).digest != first


def test_existing_gitignore_is_kept_and_extra_rules_go_to_info_exclude(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    (root / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    (root / "scratch.tmp").write_text("t", encoding="utf-8")
    plan = plan_init(root)
    assert plan.gitignore_text is None
    assert ".env" in plan.skipped_sensitive and "scratch.tmp" not in plan.files
    assert ".gitignore" in plan.files  # the user's own file is committed as it is

    commit, _count = run_init(root, plan.digest)
    assert (root / ".gitignore").read_text(encoding="utf-8") == "*.tmp\n"
    tracked = _tracked(root)
    assert ".env" not in tracked and "scratch.tmp" not in tracked and commit
    assert ".env" in (root / ".git" / "info" / "exclude").read_text(encoding="utf-8")


# --- confirming ------------------------------------------------------------------------


def test_run_init_creates_the_repository_and_first_commit(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    plan = plan_init(root)
    commit, count = run_init(root, plan.digest)
    assert count == 3  # two files and the new .gitignore
    assert _tracked(root) == {"notes.md", "slides/deck.txt", ".gitignore"}
    assert _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert _git(root, "rev-parse", "--short", "HEAD").strip() == commit
    assert "nanobot" in _git(root, "log", "-1", "--format=%an")  # fallback identity, no user config
    assert (root / ".env").exists() and (root / "node_modules" / "junk.js").exists()  # still on disk


@pytest.mark.asyncio
async def test_after_init_the_project_is_a_normal_git_repository(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    run_init(root, plan_init(root).digest)
    info = await inspect_project(root)
    assert info.kind == "git" and info.toplevel == root.resolve()


def test_a_changed_folder_is_refused_and_nothing_is_created(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    reviewed = plan_init(root).digest
    (root / "added-after-review.md").write_text("x", encoding="utf-8")
    with pytest.raises(InitError, match="changed since the preview"):
        run_init(root, reviewed)
    assert not (root / ".git").exists() and not (root / ".gitignore").exists()


def test_failure_rolls_back_what_was_created(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    plan = plan_init(root)
    real = init_repo._git

    def failing(args, **kwargs):  # noqa: ANN001, ANN003
        if args and args[0] == "commit":
            raise InitError("boom")
        return real(args, **kwargs)

    with patch.object(init_repo, "_git", side_effect=failing):
        with pytest.raises(InitError, match="boom"):
            run_init(root, plan.digest)
    assert not (root / ".git").exists() and not (root / ".gitignore").exists()
    assert (root / "notes.md").exists() and (root / ".env").exists()


def test_empty_repository_is_committed_without_a_second_init(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    _git(root, "init", "-q", "-b", "trunk")
    plan = plan_init(root)
    assert plan.existing_repo
    run_init(root, plan.digest)
    assert _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip() == "trunk"  # branch untouched
    assert "notes.md" in _tracked(root)


# --- refusals --------------------------------------------------------------------------


def test_refuses_nested_repositories_and_repositories_with_commits(tmp_path: Path) -> None:
    outer = _folder(tmp_path, "outer")
    inner = outer / "inner"
    inner.mkdir()
    _git(outer, "init", "-q", "-b", "main")
    _git(outer, "config", "user.name", "t")
    _git(outer, "config", "user.email", "t@example.com")
    _git(outer, "add", "-A")
    _git(outer, "commit", "-q", "-m", "x")
    with pytest.raises(InitError, match="inside the git repository"):
        plan_init(inner)
    with pytest.raises(InitError, match="already a git repository with commits"):
        plan_init(outer)


def test_leaves_out_large_files_and_embedded_repositories(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    (root / "video.bin").write_bytes(b"0" * (init_repo.LARGE_FILE_BYTES + 1))
    sub = root / "vendored"
    sub.mkdir()
    _git(sub, "init", "-q")
    (sub / "a.txt").write_text("a", encoding="utf-8")
    plan = plan_init(root)
    assert "video.bin" in plan.skipped_large and "video.bin" not in plan.files
    assert plan.skipped_embedded == ["vendored/"]
    assert plan.gitignore_text is not None and "/video.bin" in plan.gitignore_text
    run_init(root, plan.digest)
    assert "video.bin" not in _tracked(root)


def test_refuses_a_folder_that_is_too_big(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _folder(tmp_path)
    monkeypatch.setattr(init_repo, "MAX_FILES", 1)
    with pytest.raises(InitError, match="files would be committed"):
        plan_init(root)


def test_refuses_an_empty_folder(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / ".env").write_text("x", encoding="utf-8")  # only a secret: nothing to commit but .gitignore
    plan = plan_init(empty)  # .gitignore itself is committed, so this is allowed
    assert plan.files == [] and plan.gitignore_text is not None


# --- /code init ------------------------------------------------------------------------


def _scoped(project: Path) -> Session:
    session = Session(key="websocket:t", messages=[])
    session.metadata["workspace_scope"] = {"project_path": str(project), "access_mode": "restricted"}
    return session


def _ctx(args: str, session: Session | None) -> CommandContext:
    ctx = MagicMock(spec=CommandContext)
    ctx.args = args
    ctx.session = session
    ctx.msg = SimpleNamespace(channel="websocket", chat_id="c", metadata={})
    ctx.key = "websocket:t"
    return ctx


@pytest.mark.asyncio
async def test_code_init_preview_then_confirm(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    session = _scoped(root)
    preview = (await cmd_code(_ctx("init", session))).content
    assert "notes.md" in preview and "Nothing has been changed yet" in preview
    assert ".env" in preview  # listed as left out
    assert not (root / ".git").exists()
    assert init_preview(session) is not None

    done = (await cmd_code(_ctx("init confirm", session))).content
    assert "Created a git repository" in done and "isolated worktree" in done
    assert (root / ".git").exists() and init_preview(session) is None


@pytest.mark.asyncio
async def test_code_init_confirm_needs_a_reviewed_preview_and_cancel_forgets_it(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    session = _scoped(root)
    assert "Run `/code init` first" in (await cmd_code(_ctx("init confirm", session))).content
    await cmd_code(_ctx("init", session))
    assert "Cancelled" in (await cmd_code(_ctx("init cancel", session))).content
    assert init_preview(session) is None
    assert not (root / ".git").exists()


@pytest.mark.asyncio
async def test_code_init_confirm_refuses_a_stale_preview(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    session = _scoped(root)
    await cmd_code(_ctx("init", session))
    (root / "late.md").write_text("x", encoding="utf-8")
    reply = (await cmd_code(_ctx("init confirm", session))).content
    assert "changed since the preview" in reply
    assert not (root / ".git").exists() and init_preview(session) is None


@pytest.mark.asyncio
async def test_code_init_needs_a_project_and_reports_refusals(tmp_path: Path) -> None:
    assert "No project directory" in (await cmd_code(_ctx("init", Session(key="k", messages=[])))).content
    root = _folder(tmp_path)
    run_init(root, plan_init(root).digest)
    assert "already a git repository" in (await cmd_code(_ctx("init", _scoped(root)))).content
    assert "Usage" in (await cmd_code(_ctx("init nonsense", _scoped(_folder(tmp_path, "d2"))))).content


# --- session API (the WebUI button) ----------------------------------------------------------


def test_session_api_preview_confirm_cancel(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    session = _scoped(root)
    set_pending_direct(session, root)

    session_api.apply_coding(session, {"init": "preview", "path": str(root)})
    shown = coworker_session_status(session)["coding"]["project"]["init_preview"]
    assert shown["files"] == ["notes.md", "slides/deck.txt"] and shown["gitignore"]
    assert not (root / ".git").exists()

    session_api.apply_coding(session, {"init": "cancel", "path": str(root)})
    assert init_preview(session) is None

    session_api.apply_coding(session, {"init": "preview", "path": str(root)})
    session_api.apply_coding(session, {"init": "confirm", "path": str(root)})
    assert (root / ".git").exists()
    assert init_preview(session) is None and pending_direct(session) is None


def test_session_api_init_validation(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    other = _folder(tmp_path, "other")
    session = _scoped(root)
    with pytest.raises(SessionApiError, match="Review the files first"):
        session_api.apply_coding(session, {"init": "confirm", "path": str(root)})
    with pytest.raises(SessionApiError, match="project directory"):
        session_api.apply_coding(session, {"init": "preview", "path": str(other)})
    with pytest.raises(SessionApiError, match="preview, confirm or cancel"):
        session_api.apply_coding(session, {"init": "now", "path": str(root)})
    (root / "docs.txt").write_text("x", encoding="utf-8")
    session_api.apply_coding(session, {"init": "preview", "path": str(root)})
    (root / "late.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SessionApiError, match="changed since the preview"):
        session_api.apply_coding(session, {"init": "confirm", "path": str(root)})


# --- the agent then uses a worktree, not direct mode ---------------------------------------------


@pytest.mark.asyncio
async def test_after_init_a_coding_task_uses_a_worktree_without_consent(tmp_path: Path) -> None:
    root = _folder(tmp_path)
    session = _scoped(root)
    cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="pi",
            repos=[],
            pi=PiBackendConfig(command=[sys.executable, FAKE_PI_SCRIPT], allow_unsandboxed=True),
        )
    )
    runner = CodingRunner(cfg, tmp_path / "ws")
    run_init(root, plan_init(root).digest)
    with patch("nanobot.coworker.coding.runner._lookup_session", return_value=session):
        task, _backend, _repo = await runner.admit_async(
            brief="b", session_key="s", channel="c", chat_id="u"
        )
    assert task.mode == "worktree"  # no `ask` confirmation: it is a repository now
