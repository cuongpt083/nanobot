"""BrowserSkill Mức 2, P1 (nanobot side): the runner, journal, registry, policy and tools, against a fake bsk.

A last group runs the real bsk binary when BSK_BIN is set, for the request protocol that needs no browser.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

from nanobot.coworker.browser import policy
from nanobot.coworker.browser.journal import BrowserJournal
from nanobot.coworker.browser.registry import TOKEN_TTL_MS, BrowserSessionRegistry
from nanobot.coworker.browser.runner import BskError, BskRunner
from nanobot.coworker.browser.tools import (
    BrowserInspectTool,
    BrowserInteractTool,
    BrowserPageTool,
    BrowserSessionTool,
)
from nanobot.coworker.config import BrowserConfig

FAKE = Path(__file__).with_name("fake_bsk.py")


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_BSK_LOG", str(log))
    for name in ("FAKE_BSK_START_FAIL", "FAKE_BSK_CLAIM_FAIL", "FAKE_BSK_HANG"):
        monkeypatch.delenv(name, raising=False)
    return {"log": log, "dir": tmp_path}


def runner() -> BskRunner:
    return BskRunner(argv=(sys.executable, str(FAKE)))


def calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def registry(tmp_path: Path, **kwargs) -> tuple[BrowserSessionRegistry, BrowserJournal, FakeClock]:
    clock = FakeClock()
    journal = BrowserJournal(tmp_path / "journal")
    reg = BrowserSessionRegistry(
        runner(), journal, clock=clock, now_ms=lambda: 1_700_000_000_000, **kwargs,
    )
    return reg, journal, clock


# ---------- runner ----------

async def test_a_successful_command_returns_its_json(fake: dict[str, Path]) -> None:
    # bsk prints a list for "session list"; the runner wraps a non-object reply.
    reply = await runner().run(["session", "list"])
    assert reply == {"result": []}
    stopped = await runner().run(["session", "stop", "s-9"])
    assert stopped["stopped"] == ["s-9"]


async def test_bsk_error_envelope_becomes_a_typed_error(fake: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_BSK_START_FAIL", "1")
    with pytest.raises(BskError) as exc:
        await runner().run(["session", "start", "--request-id", "x"])
    assert exc.value.code == "no_browser_connected"
    assert exc.value.exit_code == 1
    assert "extension" in (exc.value.hint or "")


async def test_a_command_past_its_timeout_is_killed_and_reported(fake: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_BSK_HANG", "1")
    with pytest.raises(BskError) as exc:
        await runner().run(["observe", "--session", "s-1"], timeout=1)
    assert exc.value.code == "timeout"


async def test_a_missing_binary_says_how_to_install_it() -> None:
    with pytest.raises(BskError) as exc:
        await BskRunner(argv=("definitely-not-a-real-bsk-binary",)).run(["status"])
    assert exc.value.code == "not_installed"
    assert exc.value.hint


async def test_auto_start_is_off_and_home_is_passed_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def fake_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["BSK_AUTO_START"] = "1" if self.auto_start else "0"
        if self.home:
            env["BSK_HOME"] = self.home
        seen.update(env)
        return env

    monkeypatch.setattr(BskRunner, "_env", fake_env)
    await BskRunner(argv=(sys.executable, str(FAKE)), home=str(tmp_path)).run(["session", "list"])
    assert seen["BSK_AUTO_START"] == "0"
    assert seen["BSK_HOME"] == str(tmp_path)


# ---------- journal ----------

def test_a_started_session_stays_open_until_its_stop_is_recorded(tmp_path: Path) -> None:
    journal = BrowserJournal(tmp_path / "j")
    journal.append("start_ok", key="websocket:a", agent_id="main", request_id="r1", session_id="s-1")
    journal.append("start_ok", key="websocket:a", agent_id="main", request_id="r2", session_id="s-2")
    journal.append("stopped", key="websocket:a", agent_id="main", session_id="s-1")
    assert [s.session_id for s in journal.open_sessions()] == ["s-2"]


def test_a_torn_last_line_does_not_hide_earlier_events(tmp_path: Path) -> None:
    journal = BrowserJournal(tmp_path / "j")
    journal.append("start_ok", key="websocket:a", agent_id="main", request_id="r1", session_id="s-1")
    with journal.path.open("a", encoding="utf-8") as handle:
        handle.write('{"event": "stop')  # a crash mid-write
    assert [s.session_id for s in journal.open_sessions()] == ["s-1"]


def test_an_unknown_event_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        BrowserJournal(tmp_path).append("made_up")


# ---------- registry ----------

async def test_a_start_prepares_starts_claims_and_journals_in_that_order(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, journal, _ = registry(tmp_path)

    owned = await reg.start("websocket:a", "main")

    commands = [c[:3] for c in calls(fake["log"])]
    assert commands == [
        ["session", "request", commands[0][2]],
        ["session", "start", "--request-id"],
        ["session", "request", commands[0][2]],
    ]
    assert calls(fake["log"])[0][3] == "--prepare"
    assert calls(fake["log"])[2][3] == "--claim"
    events = [r["event"] for r in journal.read()]
    assert events == ["start_intent", "start_ok"]
    assert reg.current("websocket:a", "main") == owned.session_id


async def test_a_token_expires_five_minutes_ahead_and_is_a_uuid(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, journal, _ = registry(tmp_path)
    await reg.start("websocket:a", "main")
    token = journal.read()[0]["request_id"]
    expiry, _, identity = token.partition(":")
    assert int(expiry) == 1_700_000_000_000 + TOKEN_TTL_MS
    uuid.UUID(identity)


async def test_a_failed_start_is_journaled_and_owns_nothing(tmp_path: Path, fake: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_BSK_START_FAIL", "1")
    reg, journal, _ = registry(tmp_path)
    with pytest.raises(BskError) as exc:
        await reg.start("websocket:a", "main")
    assert exc.value.code == "no_browser_connected"
    assert reg.owned("websocket:a", "main") == []
    assert journal.read()[-1]["event"] == "start_failed"


async def test_a_session_that_cannot_be_claimed_is_stopped_again(tmp_path: Path, fake: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_BSK_CLAIM_FAIL", "1")
    reg, journal, _ = registry(tmp_path)
    with pytest.raises(BskError):
        await reg.start("websocket:a", "main")
    assert any(c[:2] == ["session", "stop"] for c in calls(fake["log"]))
    assert reg.owned("websocket:a", "main") == []
    assert journal.open_sessions() == []


async def test_a_conversation_may_hold_two_sessions_and_nanobot_five(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path, max_per_key=2, max_total=5)
    await reg.start("websocket:a", "main")
    await reg.start("websocket:a", "main")
    with pytest.raises(BskError) as per_key:
        await reg.start("websocket:a", "main")
    assert per_key.value.code == "limit"
    for index in range(3):
        await reg.start(f"websocket:{index}", "main")
    with pytest.raises(BskError) as total:
        await reg.start("websocket:z", "main")
    assert total.value.code == "limit"


async def test_one_conversation_cannot_stop_another_conversations_session(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path)
    mine = await reg.start("websocket:a", "main")
    with pytest.raises(BskError) as exc:
        await reg.stop("websocket:b", "main", mine.session_id)
    assert exc.value.code == "not_owned"
    with pytest.raises(BskError):
        await reg.stop("websocket:a", "guest", mine.session_id)


async def test_the_end_of_a_turn_stops_what_was_not_kept_open(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path)
    kept = await reg.start("websocket:a", "main", keep_open=True)
    closed = await reg.start("websocket:a", "main")

    stopped = await reg.close_turn("websocket:a", "main")

    assert stopped == [closed.session_id]
    assert [s.session_id for s in reg.owned("websocket:a", "main")] == [kept.session_id]


async def test_an_idle_kept_session_is_stopped_after_its_limit(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, clock = registry(tmp_path, idle_ttl_s=60)
    kept = await reg.start("websocket:a", "main", keep_open=True)
    clock.now += 61
    assert await reg.sweep_idle("websocket:a", "main") == [kept.session_id]


async def test_after_a_restart_the_journal_decides_what_to_stop(tmp_path: Path, fake: dict[str, Path]) -> None:
    journal = BrowserJournal(tmp_path / "journal")
    journal.append("start_ok", key="websocket:a", agent_id="main", request_id="r1", session_id="s-old")
    reg = BrowserSessionRegistry(runner(), journal)

    assert await reg.recover() == ["s-old"]
    assert journal.open_sessions() == []


async def test_shutdown_stops_every_owned_session(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path)
    await reg.start("websocket:a", "main", keep_open=True)
    await reg.start("websocket:b", "main", keep_open=True)
    assert len(await reg.shutdown()) == 2
    assert reg.owned("websocket:a", "main") == []


# ---------- policy ----------

def test_a_denied_domain_and_its_subdomains_are_refused() -> None:
    deny = ["gmail.com"]
    assert policy.is_denied("gmail.com", deny)
    assert policy.is_denied("mail.gmail.com", deny)
    assert not policy.is_denied("notgmail.com", deny)
    with pytest.raises(policy.PolicyError):
        policy.check_url("https://mail.gmail.com/inbox", deny)


def test_only_web_addresses_can_be_opened() -> None:
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "chrome://settings"):
        with pytest.raises(policy.PolicyError):
            policy.host_of(bad)
    assert policy.host_of("https://Example.COM./path") == "example.com"


def test_only_listed_personas_may_interact() -> None:
    allowed = ["marketer", "designer", "sales"]
    assert policy.mode_for("Sales", allowed) == policy.MODE_INTERACT
    assert policy.mode_for("researcher", allowed) == policy.MODE_READ
    assert policy.mode_for(None, allowed) == policy.MODE_READ


# ---------- tools ----------

def _tool(cls, *, persona: str | None = None, config: BrowserConfig | None = None, root: Path, reg: BrowserSessionRegistry):
    tool = cls()
    cfg = config or BrowserConfig(enabled=True)
    tool._context = lambda: (reg, cfg, "websocket:a", persona or "main")  # type: ignore[method-assign]
    return tool


async def test_navigating_to_a_denied_site_is_refused_before_bsk_is_called(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path)
    await reg.start("websocket:a", "main")
    tool = _tool(BrowserPageTool, root=tmp_path, reg=reg)
    result = await tool.execute(action="navigate", url="https://mail.google.com/")
    assert "may not open" in str(result)
    assert not any(c[0] == "navigate" for c in calls(fake["log"]))


async def test_a_read_persona_cannot_interact(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path)
    tool = _tool(BrowserInteractTool, persona="researcher", root=tmp_path, reg=reg)
    result = await tool.execute(action="click", target="@e1", session="s-1")
    assert "only read" in str(result)


async def test_an_inspect_result_has_the_shared_shape_and_the_untrusted_notice(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path)
    owned = await reg.start("websocket:a", "main")
    tool = _tool(BrowserInspectTool, root=tmp_path, reg=reg)
    result = await tool.execute(action="observe")
    body = json.loads(str(result))
    assert body["status"] == "ok"
    assert body["session"] == owned.session_id
    assert body["action"] == "inspect.observe"
    assert body["truncated"] is False
    assert "untrusted" in body["notice"]


async def test_a_large_result_is_cut_and_says_so(tmp_path: Path, fake: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from nanobot.coworker.browser import tools as browser_tools

    reg, _, _ = registry(tmp_path)
    await reg.start("websocket:a", "main")
    monkeypatch.setattr(browser_tools, "MAX_RESULT_CHARS", 20)
    tool = _tool(BrowserInspectTool, root=tmp_path, reg=reg)
    body = json.loads(str(await tool.execute(action="snapshot")))
    assert body["truncated"] is True


async def test_a_tool_without_a_session_says_to_start_one(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path)
    tool = _tool(BrowserInspectTool, root=tmp_path, reg=reg)
    result = await tool.execute(action="observe")
    assert "browser_session" in str(result)


async def test_session_start_and_stop_through_the_tool(tmp_path: Path, fake: dict[str, Path]) -> None:
    reg, _, _ = registry(tmp_path)
    tool = _tool(BrowserSessionTool, root=tmp_path, reg=reg)
    started = json.loads(str(await tool.execute(action="start")))
    assert started["status"] == "ok" and started["session"].startswith("s-")
    stopped = await tool.execute(action="stop", session=started["session"])
    assert json.loads(str(stopped))["status"] == "ok"


# ---------- the real bsk (only when BSK_BIN is set) ----------

@pytest.mark.skipif(not os.environ.get("BSK_BIN"), reason="set BSK_BIN to run against the real bsk binary")
async def test_the_real_request_protocol_refuses_a_start_with_no_browser() -> None:
    real = BskRunner(argv=(os.environ["BSK_BIN"],), home=os.environ.get("BSK_HOME"))
    token = f"{int(__import__('time').time() * 1000) + 480_000}:{uuid.uuid4()}"

    prepared = await real.run(["session", "request", token, "--prepare"])
    assert prepared["state"] == "prepared"
    with pytest.raises(BskError) as exc:
        await real.run(["session", "start", "--request-id", token])
    assert exc.value.code == "no_browser_connected"
    assert (await real.run(["session", "request", token]))["state"] == "closed"
    assert (await real.run(["session", "request", token, "--cancel"]))["state"] == "closed"


def test_the_bsk_program_comes_from_config_then_the_environment_then_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from nanobot.coworker.browser.tools import bsk_program

    monkeypatch.delenv("NANOBOT_BSK_PATH", raising=False)
    assert bsk_program(BrowserConfig()) == "bsk"
    monkeypatch.setenv("NANOBOT_BSK_PATH", "C:/app/resources/bsk.exe")
    assert bsk_program(BrowserConfig()) == "C:/app/resources/bsk.exe"
    assert bsk_program(BrowserConfig(bsk_path="D:/custom/bsk.exe")) == "D:/custom/bsk.exe"
