"""Milestone M1 tests: JSONL parsing, Pi and Agy backends, fake harnesses, security/env hygiene."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from nanobot.coworker.coding.backends.agy import AgyBackend, parse_agy_usage
from nanobot.coworker.coding.backends.base import (
    BackendEventDone,
    BackendEventError,
    BackendEventTool,
    BackendStats,
)
from nanobot.coworker.coding.backends.jsonl import (
    iter_jsonl_stream,
    parse_jsonl_line,
)
from nanobot.coworker.coding.backends.pi import PiBackend
from nanobot.coworker.config import AgyBackendConfig, PiBackendConfig

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")
FAKE_AGY_SCRIPT = str(Path(__file__).parent / "fake_agy.py")
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "agy-1.2.13"


def test_jsonl_parser_framing() -> None:
    # 1. Normal line
    res = parse_jsonl_line(b'{"key": "value"}\n')
    assert res == {"key": "value"}

    # 2. Line ending in \r\n
    res = parse_jsonl_line(b'{"key": "value"}\r\n')
    assert res == {"key": "value"}

    # 3. Line with U+2028 (Line Separator) - must NOT split, treated as code point inside line
    line_with_u2028 = '{"text": "line1\u2028line2"}\n'.encode("utf-8")
    res = parse_jsonl_line(line_with_u2028)
    assert res is not None
    assert res["text"] == "line1\u2028line2"

    # 4. Malformed JSON returns None
    assert parse_jsonl_line(b"not json\n") is None
    assert parse_jsonl_line(b"{broken\n") is None

    # 5. Empty line returns None
    assert parse_jsonl_line(b"\n") is None
    assert parse_jsonl_line(b"\r\n") is None


@pytest.mark.asyncio
async def test_agy_parser_real_fixtures() -> None:
    # Read print-ok.jsonl
    fixture_path = FIXTURES_DIR / "print-ok.jsonl"
    with open(fixture_path, "rb") as f:
        content = f.read()

    reader = asyncio.StreamReader()
    reader.feed_data(content)
    reader.feed_eof()

    events: list[dict] = []
    async for item in iter_jsonl_stream(reader):
        events.append(item)

    assert len(events) == 5
    assert events[0]["event"] == "init"
    assert events[0]["conversation_id"] == "8dec999c-71ab-4b05-8e06-3ddbd4ca7d6e"
    assert events[4]["event"] == "result"
    assert events[4]["result"]["status"] == "SUCCESS"

    usage = parse_agy_usage(events[4]["result"]["usage"])
    assert usage.input_tokens == 12345
    assert usage.output_tokens == 25
    assert usage.thinking_tokens == 24
    assert usage.total_tokens == 12370

    # Test cumulative diff
    prev = BackendStats(input_tokens=10000, output_tokens=10, total_tokens=10010)
    delta = usage.diff_from_previous(prev)
    assert delta.input_tokens == 2345
    assert delta.output_tokens == 15
    assert delta.total_tokens == 2360


@pytest.mark.asyncio
async def test_fake_agy_happy_path_and_tools(tmp_path: Path) -> None:
    config = AgyBackendConfig(
        command=[sys.executable, FAKE_AGY_SCRIPT],
        allow_unsandboxed=True,
    )
    backend = AgyBackend(config=config, global_sandbox="none")

    run = backend.start(
        brief="Create test file",
        cwd=tmp_path,
        rules="Follow instructions",
        task_id="ct-agy-1",
    )

    events = []
    async for event in run:
        events.append(event)

    assert any(isinstance(e, BackendEventTool) and e.tool_name == "write_to_file" for e in events)
    done_events = [e for e in events if isinstance(e, BackendEventDone)]
    assert len(done_events) == 1
    assert done_events[0].result.status == "succeeded"
    assert done_events[0].result.stats.total_tokens > 0
    assert done_events[0].resume_ref is not None

    # Follow up round
    run_ref = done_events[0].resume_ref
    follow_up_run = backend.follow_up(
        run_ref=run_ref,
        message="Follow up round",
        cwd=tmp_path,
        rules="Follow instructions",
        task_id="ct-agy-1",
    )

    fu_events = []
    async for event in follow_up_run:
        fu_events.append(event)

    fu_done = [e for e in fu_events if isinstance(e, BackendEventDone)]
    assert len(fu_done) == 1
    assert fu_done[0].result.status == "succeeded"
    # Follow-up delta should subtract previous cumulative total
    assert fu_done[0].result.stats.total_tokens > 0


@pytest.mark.asyncio
async def test_fake_agy_failure_modes(tmp_path: Path) -> None:
    # 1. Non-zero exit code
    config_fail = AgyBackendConfig(
        command=[sys.executable, FAKE_AGY_SCRIPT],
        allow_unsandboxed=True,
        pass_env=["FAKE_AGY_SCENARIO"],
    )
    backend_fail = AgyBackend(config=config_fail, global_sandbox="none")

    with patch.dict(os.environ, {"FAKE_AGY_SCENARIO": "exit_code:42"}):
        run = backend_fail.start(brief="test", cwd=tmp_path, rules="", task_id="t1")
        events = [e async for e in run]
        assert any(isinstance(e, BackendEventError) for e in events)
        done = [e for e in events if isinstance(e, BackendEventDone)][0]
        assert done.result.status == "error"

    # 2. Missing result event
    with patch.dict(os.environ, {"FAKE_AGY_SCENARIO": "missing_result"}):
        run = backend_fail.start(brief="test", cwd=tmp_path, rules="", task_id="t2")
        events = [e async for e in run]
        assert any(isinstance(e, BackendEventError) for e in events)
        done = [e for e in events if isinstance(e, BackendEventDone)][0]
        assert done.result.status == "error"

    # 3. Status FAILED in result
    with patch.dict(os.environ, {"FAKE_AGY_SCENARIO": "status_error"}):
        run = backend_fail.start(brief="test", cwd=tmp_path, rules="", task_id="t3")
        events = [e async for e in run]
        assert any(isinstance(e, BackendEventError) for e in events)
        done = [e for e in events if isinstance(e, BackendEventDone)][0]
        assert done.result.status == "error"
        assert done.result.raw_error_line is not None


@pytest.mark.asyncio
async def test_fake_pi_run_and_auto_cancel_ui(tmp_path: Path) -> None:
    config = PiBackendConfig(
        command=[sys.executable, FAKE_PI_SCRIPT],
        allow_unsandboxed=True,
        pass_env=["FAKE_PI_SCENARIO"],
    )
    backend = PiBackend(config=config, global_sandbox="none")

    # Set scenario to ui_dialog: Pi emits an extension_ui_request,
    # PiBackend must automatically cancel it and proceed to completion.
    with patch.dict(os.environ, {"FAKE_PI_SCENARIO": "ui_dialog"}):
        run = backend.start(
            brief="Edit a file",
            cwd=tmp_path,
            rules="Strict rules",
            task_id="ct-pi-1",
        )

        events = []
        async for event in run:
            events.append(event)

        assert any(isinstance(e, BackendEventTool) for e in events)
        done = [e for e in events if isinstance(e, BackendEventDone)][0]
        assert done.result.status == "succeeded"
        assert done.result.stats.total_tokens == 1170
        assert done.result.stats.cost == 0.0025
        assert done.resume_ref is not None

        await backend.abort()


@pytest.mark.asyncio
async def test_extra_args_denylist() -> None:
    # Denylist: --model, --effort, -p, --print, --prompt, --output-format, --conversation, -c, --continue
    for flag in ["--model", "--model=gpt-4", "-p", "--conversation", "-c", "--effort=max"]:
        with pytest.raises(ValidationError):
            AgyBackendConfig(extra_args=[flag])

    # Allowed extra args
    ok_cfg = AgyBackendConfig(extra_args=["--disable-slash-commands"])
    assert ok_cfg.extra_args == ["--disable-slash-commands"]


@pytest.mark.asyncio
async def test_env_and_argv_hygiene(tmp_path: Path) -> None:
    secret_env = {
        "ANTHROPIC_API_KEY": "sk-ant-secret-12345",
        "GEMINI_API_KEY": "secret-gemini-key",
        "OPENAI_API_KEY": "sk-openai-secret",
        "CUSTOM_VAR": "custom_val",
    }
    with patch.dict(os.environ, secret_env):
        # AgyBackend
        agy_cfg = AgyBackendConfig(
            command=[sys.executable, FAKE_AGY_SCRIPT],
            pass_env=["CUSTOM_VAR"],
            allow_unsandboxed=True,
        )
        agy_backend = AgyBackend(config=agy_cfg, global_sandbox="none")
        agy_run = agy_backend.start(brief="test brief", cwd=tmp_path, rules="", task_id="t-env-agy")
        await agy_run.__aiter__().__anext__()

        # Inspect spawned agy process
        assert agy_run.proc is not None
        child_env = agy_run._env
        assert "ANTHROPIC_API_KEY" not in child_env
        assert "GEMINI_API_KEY" not in child_env
        assert "OPENAI_API_KEY" not in child_env
        assert child_env.get("CUSTOM_VAR") == "custom_val"

        # Check agy argv
        argv = agy_run._args
        assert "--dangerously-skip-permissions" in argv
        assert "--model" not in argv
        assert "--effort" not in argv
        await agy_backend.abort()

        # PiBackend
        pi_cfg = PiBackendConfig(
            command=[sys.executable, FAKE_PI_SCRIPT],
            pass_env=["CUSTOM_VAR"],
            allow_unsandboxed=True,
        )
        pi_backend = PiBackend(config=pi_cfg, global_sandbox="none")
        pi_run = pi_backend.start(brief="test brief", cwd=tmp_path, rules="rules", task_id="t-env-pi")
        await pi_run.__aiter__().__anext__()

        assert pi_backend.proc is not None
        pi_argv = pi_backend._build_command(
            task_id="t-env-pi",
            rules="rules",
            session_dir=None,
            resume_session=None,
        )
        assert "--model" not in pi_argv
        assert "--provider" not in pi_argv
        assert "--thinking" not in pi_argv
        assert "--api-key" not in pi_argv
        await pi_backend.abort()


@pytest.mark.asyncio
async def test_steer_and_capabilities(tmp_path: Path) -> None:
    agy_cfg = AgyBackendConfig(command=[sys.executable, FAKE_AGY_SCRIPT], allow_unsandboxed=True)
    agy_backend = AgyBackend(config=agy_cfg, global_sandbox="none")
    assert agy_backend.capabilities.steer is False
    with pytest.raises(NotImplementedError):
        await agy_backend.steer("change course")

    pi_cfg = PiBackendConfig(command=[sys.executable, FAKE_PI_SCRIPT], allow_unsandboxed=True)
    pi_backend = PiBackend(config=pi_cfg, global_sandbox="none")
    assert pi_backend.capabilities.steer is True


@pytest.mark.asyncio
async def test_unsandboxed_admission(tmp_path: Path) -> None:
    # When sandbox is "none" and allow_unsandboxed is False, starts are refused
    agy_cfg = AgyBackendConfig(allow_unsandboxed=False)
    agy_backend = AgyBackend(config=agy_cfg, global_sandbox="none")
    with pytest.raises(PermissionError):
        agy_backend.start(brief="test", cwd=tmp_path, rules="", task_id="t1")

    pi_cfg = PiBackendConfig(allow_unsandboxed=False)
    pi_backend = PiBackend(config=pi_cfg, global_sandbox="none")
    with pytest.raises(PermissionError):
        pi_backend.start(brief="test", cwd=tmp_path, rules="", task_id="t2")
