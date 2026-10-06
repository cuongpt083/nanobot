"""`/code doctor`: diagnose the Pi coding runtime end to end."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.coworker.coding.backends.base import sandbox_policy_for
from nanobot.coworker.coding.pi import EXTENSION_PATH
from nanobot.coworker.coding.pi.client import PiClient
from nanobot.coworker.coding.pi.version import check_pi_version, get_pi_version, resolve_pi_binary
from nanobot.coworker.coding.runtime import SessionSpec
from nanobot.coworker.coding.sandbox import check_available
from nanobot.coworker.coding.workspace import WorkspaceManager

if TYPE_CHECKING:
    from nanobot.coworker.config import CoworkerConfig


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


def _version_text(version: tuple[int, int, int] | None) -> str:
    return ".".join(str(p) for p in version) if version else "unknown"


async def run_doctor(
    config: CoworkerConfig,
    workspace_root: Path,
    *,
    trial_prompt: bool = True,
) -> list[DoctorCheck]:
    """Run every diagnostic; each returns a check with a human-readable detail."""
    checks: list[DoctorCheck] = []
    pi_cfg = config.coding.pi

    # 1. Binary present
    resolved = resolve_pi_binary(list(pi_cfg.command))
    binary = resolved[0] if resolved else (pi_cfg.command[0] if pi_cfg.command else "pi")
    found = bool(shutil.which(binary) or Path(binary).exists())
    checks.append(DoctorCheck("pi_binary", found, binary if found else f"'{binary}' not found on PATH"))

    # 2. Version >= min_version
    min_version = pi_cfg.min_version or "1.0.0"
    version = get_pi_version(pi_command=pi_cfg.command) if found else None
    version_ok = found and check_pi_version(min_version, pi_command=pi_cfg.command)
    checks.append(
        DoctorCheck(
            "pi_version",
            version_ok,
            f"found {_version_text(version)}, required >= {min_version}",
        )
    )

    # 3. Node available (Pi runs on Node)
    node = shutil.which("node")
    checks.append(DoctorCheck("node", bool(node), node or "node not found on PATH"))

    # 4. Sandbox available
    try:
        check_available(sandbox_policy_for(config))
        checks.append(DoctorCheck("sandbox", True, config.coding.sandbox))
    except Exception as exc:
        checks.append(DoctorCheck("sandbox", False, str(exc)))

    # 5. Worktree root writable
    try:
        worktree_base = WorkspaceManager(config.coding, workspace_root).worktree_base
        worktree_base.mkdir(parents=True, exist_ok=True)
        probe = worktree_base / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        checks.append(DoctorCheck("worktree_root", True, str(worktree_base)))
    except Exception as exc:
        checks.append(DoctorCheck("worktree_root", False, str(exc)))

    if not found:
        return checks

    # 6-8. Live Pi session: extension loads, model list, trial prompt.
    client = PiClient(
        config=pi_cfg,
        sandbox_policy=sandbox_policy_for(config),
        timeout_minutes=config.coding.timeout_minutes,
        idle_timeout_minutes=config.coding.idle_timeout_minutes,
    )
    try:
        try:
            await client.start(
                cwd=workspace_root,
                session=SessionSpec(task_id="ct-doctor"),
                extension=EXTENSION_PATH if pi_cfg.extensions else None,
            )
            checks.append(DoctorCheck("extension", True, "nanobot-mode command loaded"))
        except Exception as exc:
            checks.append(DoctorCheck("extension", False, str(exc)))
            return checks

        try:
            models = await client.available_models()
            checks.append(
                DoctorCheck(
                    "pi_login",
                    bool(models),
                    f"{len(models)} model(s) available" if models else "no models; run `pi` and log in",
                )
            )
        except Exception as exc:
            checks.append(DoctorCheck("pi_login", False, str(exc)))

        if trial_prompt:
            try:
                outcome = await client.run_prompt("Reply with the single word OK.")
                ok = outcome.status == "succeeded"
                checks.append(DoctorCheck("trial_prompt", ok, f"status {outcome.status}"))
            except Exception as exc:
                checks.append(DoctorCheck("trial_prompt", False, str(exc)))
    finally:
        try:
            await client.close()
        except Exception:
            logger.debug("doctor: client close failed", exc_info=True)

    return checks


def render_doctor_report(checks: list[DoctorCheck]) -> str:
    lines = ["🩺 **Coding runtime doctor**"]
    for check in checks:
        mark = "✅" if check.ok else "❌"
        lines.append(f"{mark} `{check.name}`: {check.detail}")
    failures = [c for c in checks if not c.ok]
    if failures:
        lines.append("")
        lines.append(f"{len(failures)} check(s) failed. Fix the items above and re-run `/code doctor`.")
    else:
        lines.append("")
        lines.append("All checks passed.")
    return "\n".join(lines)
