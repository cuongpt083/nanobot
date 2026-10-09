"""Runs one ``bsk`` command and returns its JSON (BrowserSkill Mức 2, P1).

Every command is ``bsk --json <args>``. A success prints one JSON object. A failure exits non-zero and prints
the envelope ``{code, message, hint, exit_code, data}`` (checked against bsk 0.3.2). A command that runs past its
timeout, or whose caller is cancelled, has its process killed, so no ``bsk`` child outlives the call.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, cast

DEFAULT_TIMEOUT_S = 120.0
MAX_TIMEOUT_S = 300.0


class BskError(Exception):
    """A ``bsk`` call failed. ``code`` is bsk's error code when it gave one."""

    def __init__(
        self,
        code: str | None,
        message: str,
        *,
        hint: str | None = None,
        exit_code: int | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.exit_code = exit_code
        self.data = data

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "hint": self.hint}


@dataclass(frozen=True)
class BskRunner:
    """How to start bsk. ``argv`` is the program and any fixed leading arguments."""

    argv: tuple[str, ...] = ("bsk",)
    home: str | None = None
    # nanobot drives the daemon itself; bsk must not start one as a side effect of a client command.
    auto_start: bool = False

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["BSK_AUTO_START"] = "1" if self.auto_start else "0"
        if self.home:
            env["BSK_HOME"] = self.home
        return env

    async def run(self, args: list[str], *, timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
        budget = min(max(timeout, 1.0), MAX_TIMEOUT_S)
        try:
            process = await asyncio.create_subprocess_exec(
                *self.argv, "--json", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env(),
            )
        except FileNotFoundError as exc:
            raise BskError(
                "not_installed",
                "the bsk command is not installed or not on PATH",
                hint="install the BrowserSkill CLI, or set coworker.browser.bskPath",
            ) from exc
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=budget)
        except asyncio.TimeoutError as exc:
            await _kill(process)
            raise BskError(
                "timeout",
                f"bsk {args[0] if args else ''} did not finish within {budget:.0f} seconds",
                hint="the browser may be stuck; stop the session and try again",
            ) from exc
        except asyncio.CancelledError:
            await _kill(process)
            raise

        text = stdout.decode("utf-8", "replace").strip()
        if process.returncode == 0:
            if not text:
                return {}
            try:
                parsed: object = json.loads(text)
            except ValueError as exc:
                raise BskError("bad_output", "bsk printed output that is not JSON") from exc
            if isinstance(parsed, dict):
                return cast("dict[str, Any]", parsed)
            return {"result": parsed}

        envelope: dict[str, Any] = {}
        try:
            loaded: object = json.loads(text)
            if isinstance(loaded, dict):
                envelope = cast("dict[str, Any]", loaded)
        except ValueError:
            pass
        code = envelope.get("code")
        message = envelope.get("message")
        hint = envelope.get("hint")
        if not isinstance(message, str) or not message:
            message = stderr.decode("utf-8", "replace").strip() or f"bsk exited with status {process.returncode}"
        return_code: str | None = code if isinstance(code, str) else None
        raise BskError(
            return_code,
            message,
            hint=hint if isinstance(hint, str) else None,
            exit_code=process.returncode,
            data=envelope.get("data"),
        )


async def _kill(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        process.kill()
    try:
        await process.wait()
    except ProcessLookupError:
        pass
