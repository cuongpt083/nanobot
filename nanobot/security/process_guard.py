"""Guard against shell commands that kill nanobot's own processes.

An agent that starts a background job and later "cleans it up" by PID or by
image name (``Stop-Process -Id ...``, ``taskkill /IM python.exe``) can easily
terminate the gateway or the WebUI client it is talking through. This module
detects such commands so ``ExecTool`` can reject them before execution.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from nanobot.config.paths import get_data_dir
from nanobot.process_runtime import process_is_running

_KILL_VERB = re.compile(
    r"(?:\bstop-process\b|\btaskkill(?:\.exe)?\b|\bpkill\b|\bkillall\b|(?:^|[;&|(]\s*)kill\b"
    r"|\.kill\(|\bos\.kill\b|\bwmic\b[^|;&]*\bterminate\b|\.terminate\(\))",
    re.IGNORECASE,
)

# Kills selected by image name rather than PID. Matching a bare "python" would
# also match the gateway, which runs under the same interpreter name.
_NAME_SELECTOR = re.compile(
    r"(?:-name|-processname|/im|pkill|killall|get-process|tasklist)\b[^|;&]*?"
    r"['\"]?(?:python[w]?|uv|nanobot)(?:\.exe)?\b['\"]?",
    re.IGNORECASE,
)

_PID_NUMBER = re.compile(r"(?<![\w.])\d{2,10}(?![\w.])")


def _pids_from_state(payload: Any) -> set[int]:
    pids: set[int] = set()
    if not isinstance(payload, dict):
        return pids
    pid = payload.get("pid")
    if isinstance(pid, int):
        pids.add(pid)
    clients = payload.get("clients")
    if isinstance(clients, dict):
        for record in clients.values():
            if isinstance(record, dict) and isinstance(record.get("pid"), int):
                pids.add(record["pid"])
    return pids


def protected_pids(run_dir: Path | None = None) -> set[int]:
    """PIDs the agent must never terminate: self, parent, gateway and its clients."""
    pids = {os.getpid(), os.getppid()}
    directory = run_dir or (get_data_dir() / "run")
    try:
        files = list(directory.glob("gateway*.json"))
    except OSError:
        files = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pids.update(p for p in _pids_from_state(payload) if process_is_running(p))
    pids.discard(0)
    return pids


def check_kill_command(command: str, *, run_dir: Path | None = None) -> str | None:
    """Return an error message if ``command`` would kill a protected process."""
    if not _KILL_VERB.search(command):
        return None

    protected = protected_pids(run_dir)
    hit = sorted(
        int(n) for n in _PID_NUMBER.findall(command) if int(n) in protected
    )
    if hit:
        pid_list = ", ".join(str(p) for p in hit)
        return (
            f"Error: Command blocked by safety guard (would terminate nanobot's own "
            f"gateway/WebUI process: PID {pid_list}). Only stop processes you started "
            "yourself, identified by the PID returned when you launched them."
        )
    if _NAME_SELECTOR.search(command):
        return (
            "Error: Command blocked by safety guard (killing processes by name "
            "'python'/'uv'/'nanobot' would also terminate the gateway). Stop the job "
            "by the exact PID you recorded when launching it "
            "(e.g. Start-Process -PassThru)."
        )
    return None
