"""Milestone M1 tests: JSONL parsing, Pi backend, fake harnesses, security/env hygiene."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from nanobot.coworker.coding.backends.base import (
    BackendEventDone,
    BackendEventTool,
)
from nanobot.coworker.coding.backends.jsonl import (
    parse_jsonl_line,
)
from nanobot.coworker.coding.backends.pi import PiBackend
from nanobot.coworker.config import PiBackendConfig

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")


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
async def test_env_and_argv_hygiene(tmp_path: Path) -> None:
    secret_env = {
        "ANTHROPIC_API_KEY": "sk-ant-secret-12345",
        "GEMINI_API_KEY": "secret-gemini-key",
        "OPENAI_API_KEY": "sk-openai-secret",
        "CUSTOM_VAR": "custom_val",
    }
    with patch.dict(os.environ, secret_env):
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
    pi_cfg = PiBackendConfig(command=[sys.executable, FAKE_PI_SCRIPT], allow_unsandboxed=True)
    pi_backend = PiBackend(config=pi_cfg, global_sandbox="none")
    assert pi_backend.capabilities.steer is True


@pytest.mark.asyncio
async def test_unsandboxed_admission(tmp_path: Path) -> None:
    pi_cfg = PiBackendConfig(allow_unsandboxed=False)
    pi_backend = PiBackend(config=pi_cfg, global_sandbox="none")
    with pytest.raises(PermissionError):
        pi_backend.start(brief="test", cwd=tmp_path, rules="", task_id="t2")
