"""Pi version checking utility."""

from __future__ import annotations

import os
import re
import shutil
import subprocess


def resolve_pi_binary(cmd: list[str] | None = None) -> list[str]:
    """Resolve the command binary to its full executable path on Windows if needed."""
    full_cmd = list(cmd) if cmd else ["pi"]
    bin_name = full_cmd[0]
    resolved = shutil.which(bin_name)
    if not resolved and os.name == "nt":
        resolved = shutil.which(f"{bin_name}.cmd") or shutil.which(f"{bin_name}.exe")
    if resolved:
        full_cmd[0] = resolved
    return full_cmd


def get_pi_version(pi_command: list[str] | None = None) -> tuple[int, int, int] | None:
    resolved_cmd = resolve_pi_binary(pi_command)
    cmd = list(resolved_cmd)
    cmd.append("--version")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=10)
        match = re.search(r"(\d+)\.(\d+)\.(\d+)", res.stdout)
        if match:
            return int(match.group(1)), int(match.group(2)), int(match.group(3))
    except FileNotFoundError:
        return None
    except Exception:
        pass
    return None


async def check_pi_version_async(min_version: str = "1.0.0", pi_command: list[str] | None = None) -> bool:
    import asyncio
    return await asyncio.to_thread(check_pi_version, min_version, pi_command)


def check_pi_version(min_version: str = "1.0.0", pi_command: list[str] | None = None) -> bool:
    curr = get_pi_version(pi_command)
    if curr is None:
        return False
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", min_version)
    if not match:
        return True
    req = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return curr >= req
