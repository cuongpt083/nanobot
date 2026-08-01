from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install.sh"
SHELL = shutil.which("sh") or r"C:\Program Files\Git\bin\sh.exe"


def _dry_run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHON": sys.executable, "NANOBOT_SKIP_WIZARD": "1"}
    return subprocess.run(
        [SHELL, str(INSTALLER), "--dry-run", *args],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_source_and_ref_pin_the_git_install_target() -> None:
    result = _dry_run(
        "--source",
        "https://github.com/cuongpt083/nanobot.git",
        "--ref",
        "codex/pilot-completion",
    )

    assert result.returncode == 0, result.stderr
    assert "git+https://github.com/cuongpt083/nanobot.git@codex/pilot-completion" in result.stdout
    assert "Git source https://github.com/cuongpt083/nanobot.git @ codex/pilot-completion" in result.stdout
    assert "tool run --from" not in result.stdout


def test_ref_requires_a_source() -> None:
    result = _dry_run("--ref", "codex/pilot-completion")

    assert result.returncode != 0
    assert "--ref requires --source" in result.stderr
