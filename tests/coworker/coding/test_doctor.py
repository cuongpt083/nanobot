"""`/code doctor` diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from nanobot.coworker.coding.doctor import render_doctor_report, run_doctor
from nanobot.coworker.config import (
    CodingAgentConfig,
    CoworkerConfig,
    PiBackendConfig,
    RepoConfig,
)

FAKE_PI_SCRIPT = str(Path(__file__).parent / "fake_pi.py")


def _cfg(command: list[str]) -> CoworkerConfig:
    return CoworkerConfig(
        coding=CodingAgentConfig(
            enabled=True,
            repos=[RepoConfig(path=str(Path.cwd()), base_ref="main")],
            pi=PiBackendConfig(command=command, allow_unsandboxed=True),
        )
    )


@pytest.mark.asyncio
async def test_doctor_reports_all_checks(tmp_path: Path) -> None:
    checks = await run_doctor(_cfg([sys.executable, FAKE_PI_SCRIPT]), tmp_path)
    by_name = {c.name: c for c in checks}
    assert {"pi_binary", "pi_version", "node", "sandbox", "worktree_root"} <= set(by_name)
    assert by_name["pi_binary"].ok
    assert by_name["pi_version"].ok
    assert by_name["worktree_root"].ok
    assert by_name["extension"].ok
    assert by_name["pi_login"].ok
    assert by_name["trial_prompt"].ok

    report = render_doctor_report(checks)
    assert "🩺" in report and "`pi_version`" in report


@pytest.mark.asyncio
async def test_doctor_stops_when_binary_missing(tmp_path: Path) -> None:
    checks = await run_doctor(_cfg(["definitely_missing_pi_xyz"]), tmp_path)
    by_name = {c.name: c for c in checks}
    assert by_name["pi_binary"].ok is False
    # Pi-dependent checks are skipped when the binary is absent.
    assert "extension" not in by_name
    assert "trial_prompt" not in by_name
