"""Pi coding agent (rpc mode) harness backend."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

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
from nanobot.coworker.transcript import as_dict

if TYPE_CHECKING:
    from nanobot.coworker.config import PiBackendConfig


def _make_child_env(pass_env: list[str], agent_dir: str | None = None) -> dict[str, str]:
    base_keys = ("PATH", "HOME", "USER", "LANG", "TERM")
    env = {k: os.environ[k] for k in base_keys if k in os.environ}
    env.setdefault("TERM", "dumb")
    if agent_dir:
        env["PI_CODING_AGENT_DIR"] = agent_dir
    for name in pass_env:
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def parse_pi_stats(data: object) -> BackendStats:
    stats_dict = as_dict(data) or {}
    tokens = as_dict(stats_dict.get("tokens")) or {}
    cost_val = stats_dict.get("cost")
    cost = float(cost_val) if isinstance(cost_val, (int, float)) else 0.0
    return BackendStats(
        input_tokens=int(tokens.get("input") or 0),
        output_tokens=int(tokens.get("output") or 0),
        thinking_tokens=int(tokens.get("thinking") or 0),
        cache_read_tokens=int(tokens.get("cacheRead") or 0),
        total_tokens=int(tokens.get("total") or 0),
        cost=cost,
    )


class PiRun(BackendRun):
    """An active run consuming events from Pi until agent_settled or termination."""

    def __init__(
        self,
        backend: PiBackend,
        event_queue: asyncio.Queue[BackendEvent],
    ) -> None:
        self.backend = backend
        self.queue = event_queue

    async def __aiter__(self) -> AsyncIterator[BackendEvent]:
        while True:
            event = await self.queue.get()
            yield event
            if isinstance(event, (BackendEventDone, BackendEventError)):
                break


class PiBackend(CodingBackend):
    """Adapter for driving Pi coding agent in --mode rpc."""

    def __init__(
        self,
        config: PiBackendConfig,
        global_sandbox: str = "none",
    ) -> None:
        self.config = config
        self.global_sandbox = global_sandbox
        self.proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending_commands: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._current_queue: asyncio.Queue[BackendEvent] | None = None
        self._session_path: str | None = None
        self._last_stats: BackendStats = BackendStats()
        self._tool_count: int = 0
        self._last_tool: str | None = None
        self._settled_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "pi"

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(steer=True, live_stats=True)

    def _check_sandbox_admission(self) -> None:
        if self.global_sandbox == "none" and not self.config.allow_unsandboxed:
            raise PermissionError(
                "Unsandboxed Pi execution is refused because coding.sandbox is 'none' "
                "and pi.allow_unsandboxed is False."
            )

    async def _send_command(
        self,
        cmd_type: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        if not self.proc or not self.proc.stdin or self.proc.returncode is not None:
            raise RuntimeError("Pi process is not running")

        req_id = str(uuid.uuid4())
        payload = {"type": cmd_type, "id": req_id}
        if params:
            payload.update(params)

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_commands[req_id] = fut

        line = json.dumps(payload, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        await self.proc.stdin.drain()

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending_commands.pop(req_id, None)

    async def _read_loop(self) -> None:
        if not self.proc or not self.proc.stdout:
            return

        settled = False
        try:
            async for raw in iter_jsonl_stream(self.proc.stdout):
                event_type = raw.get("type")

                # 1. Responses to RPC commands
                if event_type == "response":
                    req_id = raw.get("id")
                    if req_id and req_id in self._pending_commands:
                        fut = self._pending_commands[req_id]
                        if not fut.done():
                            fut.set_result(raw)
                    continue

                # 2. Extension UI requests (dialogs block until answered)
                if event_type == "extension_ui_request":
                    dialog_id = raw.get("id")
                    if dialog_id and self.proc and self.proc.stdin:
                        reply = {
                            "type": "extension_ui_response",
                            "id": dialog_id,
                            "cancelled": True,
                        }
                        try:
                            self.proc.stdin.write(
                                json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n"
                            )
                            await self.proc.stdin.drain()
                        except Exception as e:
                            logger.debug(f"Failed to auto-cancel Pi UI request: {e}")
                    continue

                # 3. Tool execution events
                if event_type in (
                    "tool_execution_start",
                    "tool_execution_update",
                    "tool_execution_end",
                ):
                    tool_name = str(raw.get("toolName") or raw.get("tool") or "")
                    tool_id = str(raw.get("toolCallId") or "")
                    args = as_dict(raw.get("arguments") or raw.get("params")) or {}
                    state_map: dict[str, Literal["start", "update", "end"]] = {
                        "tool_execution_start": "start",
                        "tool_execution_update": "update",
                        "tool_execution_end": "end",
                    }
                    st = state_map[event_type]
                    if st == "start":
                        self._tool_count += 1
                        self._last_tool = tool_name
                    if self._current_queue:
                        await self._current_queue.put(
                            BackendEventTool(
                                tool_name=tool_name,
                                tool_call_id=tool_id,
                                parameters=args,
                                state=st,
                            )
                        )
                        await self._current_queue.put(
                            BackendEventProgress(
                                message=f"tool {tool_name}",
                                tool_count=self._tool_count,
                                last_tool=self._last_tool,
                            )
                        )
                    continue

                # 4. Message streaming
                if event_type in ("message_start", "message_update"):
                    delta = raw.get("delta") or raw.get("text")
                    if delta and self._current_queue:
                        await self._current_queue.put(BackendEventText(text=str(delta)))
                    continue

                # 5. Agent completion
                if event_type == "agent_settled":
                    settled = True
                    self._settled_task = asyncio.create_task(self._on_agent_settled())
                    continue

        except Exception as e:
            logger.error(f"Error in Pi read loop: {e}")
            if self._current_queue and not settled:
                await self._current_queue.put(BackendEventError(error=str(e)))
        finally:
            if self._settled_task:
                try:
                    await self._settled_task
                except Exception as e:
                    logger.debug(f"Error waiting for settled task: {e}")

            # Wake up any pending RPC futures
            for fut in self._pending_commands.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Pi process closed"))
            self._pending_commands.clear()

            # If terminated without agent_settled and queue is waiting
            if self._current_queue and not settled:
                code = self.proc.returncode if self.proc else None
                err_msg = f"Pi process terminated unexpectedly (exit code {code})"
                await self._current_queue.put(BackendEventError(error=err_msg))

    async def _on_agent_settled(self) -> None:
        response_text = ""
        try:
            resp_data = await self._send_command("get_last_assistant_text", timeout=5.0)
            data_dict = as_dict(resp_data.get("data")) or {}
            response_text = str(
                data_dict.get("text")
                or data_dict.get("content")
                or data_dict.get("response")
                or ""
            )
        except Exception as e:
            logger.debug(f"Failed to get_last_assistant_text: {e}")

        try:
            stats_resp = await self._send_command("get_session_stats", timeout=5.0)
            st_data = as_dict(stats_resp.get("data")) or {}
            self._last_stats = parse_pi_stats(st_data)
            if not self._session_path:
                self._session_path = st_data.get("sessionFile")
        except Exception as e:
            logger.debug(f"Failed to get_session_stats: {e}")

        if self._current_queue:
            res = BackendResult(
                status="succeeded",
                response=response_text,
                summary=response_text,
                stats=self._last_stats,
            )
            await self._current_queue.put(
                BackendEventDone(
                    result=res,
                    resume_ref=self._session_path,
                )
            )

    def _build_command(
        self,
        *,
        task_id: str,
        rules: str,
        session_dir: Path | None,
        resume_session: str | None,
    ) -> list[str]:
        args = list(self.config.command)
        args.extend(["--mode", "rpc", "--name", task_id])

        if session_dir:
            args.extend(["--session-dir", str(session_dir)])
        if resume_session:
            args.extend(["--session", resume_session])
        if self.config.tools:
            args.extend(["--tools", ",".join(self.config.tools)])
        if not self.config.extensions:
            args.append("--no-extensions")
        if not self.config.trust_project_files:
            args.append("--no-approve")
        if rules:
            args.extend(["--append-system-prompt", rules])

        return args

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
        args = self._build_command(
            task_id=task_id,
            rules=rules,
            session_dir=session_dir,
            resume_session=None,
        )
        env = _make_child_env(self.config.pass_env, self.config.agent_dir)
        queue: asyncio.Queue[BackendEvent] = asyncio.Queue()
        self._current_queue = queue

        async def _launch_and_prompt() -> None:
            self.proc = await spawn_process_group(args, cwd=cwd, env=env, stdin_pipe=True)
            self._reader_task = asyncio.create_task(self._read_loop())
            # Send initial prompt
            await self._send_command("prompt", {"message": brief})

        asyncio.create_task(_launch_and_prompt())
        return PiRun(self, queue)

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
        queue: asyncio.Queue[BackendEvent] = asyncio.Queue()
        self._current_queue = queue

        async def _send_or_relaunch() -> None:
            # If process is still alive, send prompt directly to same session
            if self.proc and self.proc.returncode is None:
                await self._send_command("prompt", {"message": message})
                return

            # Otherwise relaunch with --session
            args = self._build_command(
                task_id=task_id,
                rules=rules,
                session_dir=session_dir,
                resume_session=run_ref,
            )
            env = _make_child_env(self.config.pass_env, self.config.agent_dir)
            self.proc = await spawn_process_group(args, cwd=cwd, env=env, stdin_pipe=True)
            self._reader_task = asyncio.create_task(self._read_loop())
            await self._send_command("prompt", {"message": message})

        asyncio.create_task(_send_or_relaunch())
        return PiRun(self, queue)

    async def steer(self, message: str) -> None:
        await self._send_command("steer", {"message": message})

    async def abort(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                await self._send_command("abort", timeout=5.0)
            except Exception:
                pass
            await terminate_process_group(self.proc, timeout=5.0)

    async def stats(self) -> BackendStats:
        if self.proc and self.proc.returncode is None:
            try:
                res = await self._send_command("get_session_stats", timeout=5.0)
                data = as_dict(res.get("data")) or {}
                self._last_stats = parse_pi_stats(data)
            except Exception:
                pass
        return self._last_stats
