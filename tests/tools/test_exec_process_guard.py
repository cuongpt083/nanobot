"""ExecTool must refuse to kill the gateway, its clients, or python by name."""

from __future__ import annotations

import json
import os

import pytest

from nanobot.agent.tools.shell import ExecTool
from nanobot.security import process_guard


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    run = tmp_path / "run"
    run.mkdir()
    (run / "gateway.json").write_text(json.dumps({"pid": 2604}), encoding="utf-8")
    (run / "gateway.clients.json").write_text(
        json.dumps({"clients": {"t": {"pid": 11820, "kind": "webui"}}}), encoding="utf-8"
    )
    monkeypatch.setattr(process_guard, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(process_guard, "process_is_running", lambda pid: True)
    return run


@pytest.mark.parametrize(
    "command",
    [
        'powershell -Command "Stop-Process -Id 2604, 11820 -Force"',
        "taskkill /PID 11820 /F",
        "kill -9 2604",
        f"kill {os.getpid()}",
        "Stop-Process -Name python -Force",
        "taskkill /IM python.exe /F",
        "pkill -f python",
        'powershell -Command "Get-Process python | Stop-Process -Force"',
    ],
)
def test_kill_of_protected_process_is_blocked(run_dir, command):
    result = ExecTool()._guard_command(command, str(run_dir))
    assert result is not None
    assert "safety guard" in result.lower()


@pytest.mark.parametrize(
    "command",
    [
        "Stop-Process -Id 99999 -Force",
        "taskkill /PID 99999 /F",
        "kill 99999",
        "python scripts/run.py --workers 2604",
        "echo 2604",
    ],
)
def test_unrelated_commands_are_allowed(run_dir, command):
    assert ExecTool()._guard_command(command, str(run_dir)) is None


def test_stale_pid_is_not_protected(run_dir, monkeypatch):
    monkeypatch.setattr(process_guard, "process_is_running", lambda pid: False)
    assert "2604" not in {str(p) for p in process_guard.protected_pids(run_dir)}
