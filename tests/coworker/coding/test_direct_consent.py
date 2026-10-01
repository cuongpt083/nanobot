"""Consent for in-place edits: session API section, /code direct, status, pending request, routes."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nanobot.command.router import CommandContext
from nanobot.coworker import session_api
from nanobot.coworker.coding.commands import cmd_code
from nanobot.coworker.coding.project import (
    DirectConfirmationError,
    ProjectError,
    direct_allowed,
    grant_direct,
    pending_direct,
    revoke_direct,
    set_pending_direct,
)
from nanobot.coworker.coding.runner import CodingRunner
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


def _project(tmp_path: Path, name: str = "docs") -> Path:
    path = tmp_path / name
    path.mkdir()
    (path / "notes.md").write_text("x", encoding="utf-8")
    return path


def _scoped(project: Path | None, key: str = "websocket:t") -> Session:
    session = Session(key=key, messages=[])
    if project is not None:
        session.metadata["workspace_scope"] = {
            "project_path": str(project),
            "access_mode": "restricted",
        }
    return session


# --- session API section ---------------------------------------------------------------


def test_apply_coding_grants_and_revokes_for_the_chat_project(tmp_path: Path) -> None:
    project = _project(tmp_path)
    session = _scoped(project)
    session_api.apply_coding(session, {"direct_ok": True, "path": str(project)})
    assert direct_allowed(session, project)
    session_api.apply_coding(session, {"direct_ok": False, "path": str(project)})
    assert not direct_allowed(session, project)


def test_apply_coding_rejects_other_paths_and_bad_input(tmp_path: Path) -> None:
    project = _project(tmp_path)
    other = _project(tmp_path, "other")
    session = _scoped(project)
    for payload in (
        {"direct_ok": True, "path": str(other)},  # not this chat's project
        {"direct_ok": "yes", "path": str(project)},
        {"direct_ok": True},
        {"direct_ok": True, "path": ""},
    ):
        with pytest.raises(SessionApiError) as exc:
            session_api.apply_coding(session, payload)
        assert exc.value.status == 400
    assert not direct_allowed(session, other)
    with pytest.raises(SessionApiError):  # a chat without a chosen project has nothing to allow
        session_api.apply_coding(_scoped(None), {"direct_ok": True, "path": str(project)})


def test_granting_clears_the_pending_request(tmp_path: Path) -> None:
    project = _project(tmp_path)
    session = _scoped(project)
    set_pending_direct(session, project)
    assert pending_direct(session) == str(project.resolve())
    grant_direct(session, project)
    assert pending_direct(session) is None
    set_pending_direct(session, project)
    revoke_direct(session, project)  # "not now" also clears the question
    assert pending_direct(session) is None


def test_every_session_section_is_routable() -> None:
    from nanobot.webui import ws_http

    assert set(ws_http._COWORKER_SECTIONS.split("|")) == set(session_api.SECTIONS)
    for section in session_api.SECTIONS:
        path = ws_http.GatewayHTTPHandler._webui_mutation_path(
            f"session.coworker.{section}", {"key": "websocket:abc"}
        )
        assert path == f"/api/sessions/websocket%3Aabc/coworker/{section}"


# --- status ----------------------------------------------------------------------------


def test_status_exposes_the_project_and_consent(tmp_path: Path) -> None:
    project = _project(tmp_path)
    session = _scoped(project)
    info = coworker_session_status(session)["coding"]["project"]
    assert info["path"] == str(project.resolve())
    assert info["direct_allowed"] is False
    assert info["pending_direct"] is None
    assert info["non_git"] == "ask"

    set_pending_direct(session, project)
    grant_direct(session, project)
    info = coworker_session_status(session)["coding"]["project"]
    assert info["direct_allowed"] is True and info["pending_direct"] is None


def test_status_without_a_chosen_project() -> None:
    info = coworker_session_status(_scoped(None))["coding"]["project"]
    assert info["path"] is None and info["direct_allowed"] is False


# --- /code direct ----------------------------------------------------------------------


def _ctx(args: str, session: Session | None) -> CommandContext:
    ctx = MagicMock(spec=CommandContext)
    ctx.args = args
    ctx.session = session
    ctx.msg = SimpleNamespace(channel="websocket", chat_id="c", metadata={})
    ctx.key = "websocket:t"
    return ctx


@pytest.mark.asyncio
async def test_code_direct_allow_status_revoke(tmp_path: Path) -> None:
    project = _project(tmp_path)
    session = _scoped(project)
    assert "not allowed" in (await cmd_code(_ctx("direct", session))).content
    assert "may edit" in (await cmd_code(_ctx("direct allow", session))).content
    assert direct_allowed(session, project)
    assert "**allowed**" in (await cmd_code(_ctx("direct status", session))).content
    assert "no longer" in (await cmd_code(_ctx("direct revoke", session))).content
    assert not direct_allowed(session, project)
    assert "Usage" in (await cmd_code(_ctx("direct nonsense", session))).content


@pytest.mark.asyncio
async def test_code_direct_needs_a_project(tmp_path: Path) -> None:
    reply = await cmd_code(_ctx("direct allow", _scoped(None)))
    assert "No project directory" in reply.content
    assert "No project directory" in (await cmd_code(_ctx("direct allow", None))).content


# --- admission: pending request and sandbox guidance -------------------------------------


def _runner(tmp_path: Path, *, allow_unsandboxed: bool = True) -> CodingRunner:
    cfg = CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            default_backend="pi",
            repos=[],
            pi=PiBackendConfig(
                command=[sys.executable, FAKE_PI_SCRIPT], allow_unsandboxed=allow_unsandboxed
            ),
        )
    )
    return CodingRunner(cfg, tmp_path / "ws")


@pytest.mark.asyncio
async def test_unconfirmed_direct_admission_leaves_a_pending_request(tmp_path: Path) -> None:
    project = _project(tmp_path)
    session = _scoped(project)
    runner = _runner(tmp_path)
    with patch("nanobot.coworker.coding.runner._lookup_session", return_value=session):
        with pytest.raises(DirectConfirmationError):
            await runner.admit_async(brief="b", session_key="s", channel="c", chat_id="u")
    assert pending_direct(session) == str(project.resolve())
    assert runner.registry.count_active() == 0


@pytest.mark.asyncio
async def test_unsandboxed_refusal_says_how_to_fix_it(tmp_path: Path) -> None:
    project = _project(tmp_path)
    runner = _runner(tmp_path, allow_unsandboxed=False)
    with patch("nanobot.coworker.coding.runner._lookup_session", return_value=_scoped(project)):
        with pytest.raises(ProjectError, match="Settings > Capabilities > Coworker > Coding"):
            await runner.admit_async(brief="b", session_key="s", channel="c", chat_id="u")
    assert runner.registry.count_active() == 0


@pytest.fixture(autouse=True)
def _config_override():
    set_coworker_config_override(CoworkerConfig())
    yield
    set_coworker_config_override(None)
