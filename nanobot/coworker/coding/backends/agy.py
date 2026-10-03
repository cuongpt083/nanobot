"""Google Antigravity CLI (agy) coding harness backend."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger

from nanobot.coworker.coding.backends.base import (
    BackendCapabilities,
    BackendEvent,
    BackendEventDone,
    BackendEventError,
    BackendEventProgress,
    BackendEventText,
    BackendEventTool,
    BackendResult,
    BackendRun,
    BackendStats,
    CodingBackend,
)
from nanobot.coworker.coding.backends.jsonl import (
    iter_jsonl_stream,
    spawn_process_group,
    terminate_process_group,
)
from nanobot.coworker.coding.sandbox import (
    WINDOWS_ENV_KEYS,
    SandboxPolicy,
    check_available,
    wrap_argv,
)
from nanobot.coworker.transcript import as_dict

if TYPE_CHECKING:
    from nanobot.coworker.config import AgyBackendConfig


def _make_child_env(pass_env: list[str]) -> dict[str, str]:
    base_keys = ("PATH", "HOME", "USER", "LANG", "TERM")
    if os.name == "nt":  # Windows tools cannot locate the profile / system dirs without these
        base_keys += WINDOWS_ENV_KEYS
    env ={k: os.environ[k] for k in base_keys if k in os.environ}
    env.setdefault("TERM", "dumb")
    # Forward explicit pass_env vars (never forwarding LLM provider keys by default)
    for name in pass_env:
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def parse_agy_usage(raw_usage: object) -> BackendStats:
    usage_dict = as_dict(raw_usage) or {}
    return BackendStats(
        input_tokens=int(usage_dict.get("input_tokens") or 0),
        output_tokens=int(usage_dict.get("output_tokens") or 0),
        thinking_tokens=int(usage_dict.get("thinking_tokens") or 0),
        cache_read_tokens=int(usage_dict.get("cache_read_tokens") or 0),
        total_tokens=int(usage_dict.get("total_tokens") or 0),
    )


class AgyRun(BackendRun):
    """An active agy run consuming stream-json events from a subprocess."""

    def __init__(
        self,
        *,
        args: list[str],
        cwd: Path,
        env: dict[str, str],
        stdin_content: str | None = None,
        cumulative_stats: BackendStats = BackendStats(),
    ) -> None:
        self._args = args
        self._cwd = cwd
        self._env = env
        self._stdin_content = stdin_content
        self._cumulative_stats = cumulative_stats
        self.proc: asyncio.subprocess.Process | None = None
        self.conversation_id: str | None = None
        self.round_stats: BackendStats = BackendStats()
        self.last_cumulative_stats: BackendStats = cumulative_stats

    async def __aiter__(self) -> AsyncIterator[BackendEvent]:
        self.proc = await spawn_process_group(
            self._args,
            cwd=self._cwd,
            env=self._env,
            stdin_pipe=bool(self._stdin_content),
        )

        if self._stdin_content and self.proc.stdin:
            try:
                self.proc.stdin.write(self._stdin_content.encode("utf-8"))
                await self.proc.stdin.drain()
                self.proc.stdin.close()
            except Exception as e:
                logger.warning(f"Failed writing to agy stdin: {e}")

        result_event_seen = False
        tool_count = 0
        last_tool: str | None = None

        if self.proc.stdout:
            async for raw in iter_jsonl_stream(self.proc.stdout):
                event_type = raw.get("event")

                if event_type == "init":
                    self.conversation_id = raw.get("conversation_id")
                    continue

                if event_type == "step_update":
                    update = as_dict(raw.get("step_update")) or {}
                    if not self.conversation_id:
                        self.conversation_id = update.get("conversation_id")

                    step_type = update.get("step_type")
                    if step_type == "tool":
                        tool_name = str(update.get("tool_name") or "")
                        tool_info = as_dict(update.get("tool_info")) or {}
                        params = as_dict(tool_info.get("parameters")) or {}
                        state_val: Literal["start", "update", "end"] = (
                            "end" if update.get("state") == "DONE" else "start"
                        )
                        if state_val == "start":
                            tool_count += 1
                            last_tool = tool_name
                        yield BackendEventTool(
                            tool_name=tool_name,
                            tool_call_id=str(update.get("step_index") or ""),
                            parameters=params,
                            state=state_val,
                        )
                        yield BackendEventProgress(
                            message=f"tool {tool_name}",
                            tool_count=tool_count,
                            last_tool=last_tool,
                        )
                    elif text := update.get("text_delta"):
                        yield BackendEventText(text=str(text))
                    continue

                if event_type == "result":
                    result_event_seen = True
                    res = as_dict(raw.get("result")) or {}
                    status = str(res.get("status") or "")
                    self.conversation_id = res.get("conversation_id") or self.conversation_id
                    response = str(res.get("response") or "")

                    new_cumulative = parse_agy_usage(res.get("usage"))
                    self.round_stats = new_cumulative.diff_from_previous(self._cumulative_stats)
                    self.last_cumulative_stats = new_cumulative

                    if status == "SUCCESS":
                        backend_res = BackendResult(
                            status="succeeded",
                            response=response,
                            summary=response,
                            stats=self.round_stats,
                        )
                        yield BackendEventDone(
                            result=backend_res,
                            resume_ref=self.conversation_id,
                        )
                    else:
                        err_msg = str(res.get("error") or f"agy status: {status}")
                        raw_line = json.dumps(raw, ensure_ascii=False)
                        yield BackendEventError(error=err_msg, raw_line=raw_line)
                        yield BackendEventDone(
                            result=BackendResult(
                                status="error",
                                response=response,
                                summary=response,
                                stats=self.round_stats,
                                error=err_msg,
                                raw_error_line=raw_line,
                            ),
                            resume_ref=self.conversation_id,
                        )
                    break

        await self.proc.wait()

        if not result_event_seen:
            stderr_out = ""
            if self.proc.stderr:
                try:
                    stderr_bytes = await self.proc.stderr.read()
                    stderr_out = stderr_bytes.decode("utf-8", errors="replace").strip()
                except Exception:
                    pass
            err_msg = (
                f"agy exited with code {self.proc.returncode} before emitting result: {stderr_out}"
                if self.proc.returncode != 0
                else "agy exited without emitting result event"
            )
            yield BackendEventError(error=err_msg, raw_line=stderr_out or None)
            yield BackendEventDone(
                result=BackendResult(
                    status="error",
                    error=err_msg,
                    raw_error_line=stderr_out or None,
                    stats=BackendStats(),
                ),
                resume_ref=self.conversation_id,
            )


class AgyBackend(CodingBackend):
    """Adapter for driving Google Antigravity CLI in headless mode."""

    def __init__(
        self,
        config: AgyBackendConfig,
        global_sandbox: str = "none",
        sandbox_policy: SandboxPolicy | None = None,
    ) -> None:
        self.config = config
        self.global_sandbox = global_sandbox
        self.sandbox_policy = sandbox_policy or SandboxPolicy(mode=global_sandbox)
        self._current_run: AgyRun | None = None
        self._cumulative_stats: BackendStats = BackendStats()

    @property
    def name(self) -> str:
        return "agy"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(steer=False, live_stats=False)

    def _check_sandbox_admission(self) -> None:
        if self.global_sandbox == "none" and not self.config.allow_unsandboxed:
            raise PermissionError(
                "Unsandboxed agy execution is refused because coding.sandbox is 'none' "
                "and agy.allow_unsandboxed is False."
            )
        check_available(self.sandbox_policy)

    def _sandboxed(self, args: list[str], cwd: Path, env: dict[str, str]) -> list[str]:
        """Wrap the harness in the OS sandbox: only its project and its login state are writable."""
        return wrap_argv(
            args,
            policy=self.sandbox_policy,
            cwd=cwd,
            env=env,
            state_dirs=[Path.home() / ".gemini"],
        )

    def _build_args(
        self,
        *,
        prompt: str,
        conversation_id: str | None = None,
    ) -> tuple[list[str], str | None]:
        """Return (argv, stdin_json_if_large)."""
        args = list(self.config.command)
        args.extend(["--output-format", "stream-json", "--dangerously-skip-permissions"])

        if self.config.agy_sandbox:
            args.append("--sandbox")
        if self.config.mode:
            args.extend(["--mode", self.config.mode])
        if self.config.extra_args:
            args.extend(self.config.extra_args)

        if conversation_id:
            args.extend(["--conversation", conversation_id])

        # If prompt is larger than ~100 KB, feed via stream-json stdin. Through wsl.exe the whole
        # command line must fit Windows' 32 K limit, so switch much earlier there.
        limit = 20_000 if self.sandbox_policy.mode == "wsl" else 100_000
        if len(prompt.encode("utf-8")) > limit:
            args.extend(["--input-format", "stream-json", "-p", ""])
            stdin_data = json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
            return args, stdin_data

        args.extend(["-p", prompt])
        return args, None

    def start(
        self,
        *,
        brief: str,
        cwd: Path,
        rules: str,
        task_id: str,
        session_dir: Path | None = None,
    ) -> BackendRun:
        self._check_sandbox_admission()
        full_prompt = f"{rules}\n\n{brief}" if rules else brief
        args, stdin_data = self._build_args(prompt=full_prompt)
        env = _make_child_env(self.config.pass_env)
        args = self._sandboxed(args, cwd, env)

        run = AgyRun(
            args=args,
            cwd=cwd,
            env=env,
            stdin_content=stdin_data,
            cumulative_stats=self._cumulative_stats,
        )
        self._current_run = run
        return run

    def follow_up(
        self,
        *,
        run_ref: str,
        message: str,
        cwd: Path,
        rules: str,
        task_id: str,
        session_dir: Path | None = None,
    ) -> BackendRun:
        self._check_sandbox_admission()
        args, stdin_data = self._build_args(prompt=message, conversation_id=run_ref)
        env = _make_child_env(self.config.pass_env)
        args = self._sandboxed(args, cwd, env)

        # Update base cumulative stats from last run if known
        if self._current_run:
            self._cumulative_stats = self._current_run.last_cumulative_stats

        run = AgyRun(
            args=args,
            cwd=cwd,
            env=env,
            stdin_content=stdin_data,
            cumulative_stats=self._cumulative_stats,
        )
        self._current_run = run
        return run

    async def steer(self, message: str) -> None:
        raise NotImplementedError(
            "agy tasks cannot be steered mid-run; use abort then /code resume <id> <message>"
        )

    async def abort(self) -> None:
        if self._current_run and self._current_run.proc:
            await terminate_process_group(self._current_run.proc)

    async def stats(self) -> BackendStats:
        if self._current_run:
            return self._current_run.round_stats
        return self._cumulative_stats
