"""Pi version checking utility."""

from __future__ import annotations

import re
import shutil
import subprocess


def get_pi_version(pi_command: list[str] | None = None) -> tuple[int, int, int]:
    cmd = list(pi_command) if pi_command else [shutil.which("pi.cmd") or shutil.which("pi") or "pi"]
    cmd.append("--version")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", res.stdout)
        if match:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
    except Exception:
        pass
    return (0, 0, 0)


def check_pi_version(min_version: str = "1.0.0", pi_command: list[str] | None = None) -> bool:
    curr = get_pi_version(pi_command)
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", min_version)
    if not match:
        return True
    req = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return curr >= req
