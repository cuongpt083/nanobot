"""PiClient implementing CodingRuntime via JSONL RPC protocol."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.coworker.coding.backends.base import (
    BackendStats,
)
from nanobot.coworker.coding.backends.pi import parse_pi_stats
from nanobot.coworker.coding.pi.protocol import (
    Command,
    Event,
    Response,
    parse_rpc_event,
)
from nanobot.coworker.coding.pi.questions import QuestionRouter
from nanobot.coworker.coding.pi.transport import JsonlChannel
from nanobot.coworker.coding.pi.version import check_pi_version_async, resolve_pi_binary
from nanobot.coworker.coding.runtime import CodingRuntime, ModelSpec, RunOutcome, SessionSpec
from nanobot.coworker.coding.sandbox import WINDOWS_ENV_KEYS, SandboxPolicy, wrap_argv
from nanobot.coworker.config import PiBackendConfig
from nanobot.coworker.transcript import as_dict


class EventSubscription:
    """Subscription queue for streaming Pi events."""

    def __init__(self, maxsize: int = 1000) -> None:
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)

    async def put(self, event: Event) -> None:
        if self.queue.full():
            # If full, drop message_update events to prevent lagging lifecycle/tools
            if event.type == "message_update":
                return
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await self.queue.put(event)

    def __aiter__(self) -> AsyncIterator[Event]:
        return self

    async def __anext__(self) -> Event:
        return await self.queue.get()


class PiClient(CodingRuntime):
    """Client for driving Pi in RPC mode."""

    def __init__(
        self,
        config: PiBackendConfig,
        *,
        sandbox_policy: SandboxPolicy | None = None,
        timeout_minutes: float = 45,
        idle_timeout_minutes: float = 10,
        question_router: QuestionRouter | None = None,
    ) -> None:
        self.config = config
        self.sandbox_policy = sandbox_policy or SandboxPolicy(mode="none")
        self.timeout_minutes = timeout_minutes
        self.idle_timeout_minutes = idle_timeout_minutes
        self.question_router = question_router
        self.channel = JsonlChannel()
        self._pending_requests: dict[str, asyncio.Future[Response]] = {}
        self._subscriptions: list[EventSubscription] = []
        self._reader_task: asyncio.Task[None] | None = None
        self._ui_tasks: set[asyncio.Task[None]] = set()
        self._last_stats = BackendStats()
        self._last_response_text = ""
        self._cwd: Path | None = None
        self._session_spec: SessionSpec | None = None

    async def start(
        self,
        *,
        cwd: Path,
        session: SessionSpec,
        extension: Path | None = None,
        contract_file: Path | None = None,
        model: ModelSpec | None = None,
    ) -> None:
        self._cwd = cwd
        self._session_spec = session

        await self._preflight()

        args = resolve_pi_binary(list(self.config.command))
        args.extend(["--mode", "rpc"])
        if session.task_id:
            args.extend(["--name", session.task_id])
        if session.session_file:
            args.extend(["--session", str(session.session_file)])
        elif session.session_dir:
            args.extend(["--session-dir", str(session.session_dir)])
        else:
            args.append("--no-session")

        if extension:
            args.extend(["--no-extensions", "--extension", str(extension)])
        elif not self.config.extensions:
            args.append("--no-extensions")

        if self.config.tools:
            args.extend(["--tools", ",".join(self.config.tools)])
        if not self.config.trust_project_files:
            args.append("--no-approve")

        if model:
            if model.provider:
                args.extend(["--provider", model.provider])
            if model.model:
                target_model = model.model
                if model.thinking:
                    target_model = f"{target_model}:{model.thinking}"
                args.extend(["--model", target_model])

        base_keys = ("PATH", "HOME", "USER", "LANG", "TERM")
        if os.name == "nt":
            base_keys += WINDOWS_ENV_KEYS
        env = {k: os.environ[k] for k in base_keys if k in os.environ}
        env.setdefault("TERM", "dumb")
        for k in self.config.pass_env:
            if k in os.environ:
                env[k] = os.environ[k]

        if self.config.agent_dir:
            env["PI_CODING_AGENT_DIR"] = self.config.agent_dir
        if contract_file:
            env["NANOBOT_TASK_CONTRACT"] = str(contract_file)

        state = Path(self.config.agent_dir).expanduser() if self.config.agent_dir else Path.home() / ".pi"
        extra_rw = [session.session_dir] if session.session_dir else []
        argv = wrap_argv(args, policy=self.sandbox_policy, cwd=cwd, env=env, state_dirs=[state], extra_rw=extra_rw)

        await self.channel.start(argv, cwd=cwd, env=env)
        self._reader_task = asyncio.create_task(self._read_loop())

        await self._handshake(extension=extension, model=model)

    async def _preflight(self) -> None:
        min_ver = self.config.min_version or "1.0.0"
        ok = await check_pi_version_async(min_ver, pi_command=self.config.command)
        if not ok:
            raise RuntimeError(
                f"Pi executable version does not satisfy minimum required version {min_ver}"
            )

    async def _handshake(self, extension: Path | None = None, model: ModelSpec | None = None) -> None:
        try:
            state_resp = await self.request("get_state", timeout=10.0)
            if not state_resp.success:
                raise RuntimeError(f"Pi get_state failed: {state_resp.error}")
            state_data = as_dict(state_resp.data) or {}
            if "model" in state_data and not state_data.get("model") and model and model.model:
                raise RuntimeError("Pi reported empty or invalid model state")

            if extension:
                cmds_resp = await self.request("get_commands", timeout=10.0)
                if not cmds_resp.success:
                    raise RuntimeError(f"Pi get_commands failed: {cmds_resp.error}")
                cmds_data = as_dict(cmds_resp.data) or {}
                cmd_list = [c.get("name") for c in cmds_data.get("commands", []) if isinstance(c, dict)]
                if "nanobot-mode" not in cmd_list:
                    raise RuntimeError("Pi extension failed to load: nanobot-mode command missing")
        except Exception as e:
            await self.close()
            raise RuntimeError(f"Pi post-spawn handshake failed: {e}") from e

    async def _read_loop(self) -> None:
        try:
            async for raw in self.channel.records():
                if raw.get("type") == "response":
                    resp = Response.from_dict(raw)
                    fut = self._pending_requests.pop(resp.id, None)
                    if fut and not fut.done():
                        fut.set_result(resp)
                    continue

                # Handle extension UI requests (ask_coordinator dialogs & fire-and-forget notifications)
                if raw.get("type") == "extension_ui_request":
                    req_id = raw.get("id", "")
                    method = raw.get("method", "")
                    title = raw.get("title", "")
                    # Dialog methods need response back to Pi
                    if method in ("select", "confirm", "input", "editor") and req_id:
                        if self.question_router:
                            task_id = self._session_spec.task_id if self._session_spec else "unknown"

                            async def _handle_and_reply(rid: str, meth: str, tit: str, m_raw: dict[str, Any]):
                                try:
                                    res = await self.question_router.handle_extension_ui_request(
                                        request_id=rid,
                                        task_id=task_id,
                                        method=meth,
                                        title=tit,
                                        message=m_raw.get("message", ""),
                                        options=m_raw.get("options"),
                                    )
                                    reply = {"type": "extension_ui_response", "id": rid}
                                    if res.get("cancelled"):
                                        reply["cancelled"] = True
                                    elif "confirmed" in res and meth == "confirm":
                                        reply["confirmed"] = res["confirmed"]
                                    elif "value" in res:
                                        reply["value"] = res["value"]
                                    else:
                                        reply["cancelled"] = True
                                    await self.channel.send(reply)
                                except Exception as exc:
                                    logger.error(f"Failed handling extension_ui_request {rid}: {exc}")
                                    try:
                                        await self.channel.send({"type": "extension_ui_response", "id": rid, "cancelled": True})
                                    except Exception:
                                        pass

                            t = asyncio.create_task(_handle_and_reply(req_id, method, title, raw))
                            self._ui_tasks.add(t)
                            t.add_done_callback(self._ui_tasks.discard)
                        else:
                            # Auto-cancel if no question router configured
                            t = asyncio.create_task(
                                self.channel.send({"type": "extension_ui_response", "id": req_id, "cancelled": True})
                            )
                            self._ui_tasks.add(t)
                            t.add_done_callback(self._ui_tasks.discard)

                event = parse_rpc_event(raw)
                for sub in list(self._subscriptions):
                    await sub.put(event)
        except Exception as e:
            logger.debug(f"PiClient read loop exception: {e}")
        finally:
            for fut in self._pending_requests.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Pi process terminated"))
            self._pending_requests.clear()

    def events(self, *, maxsize: int = 1000) -> EventSubscription:
        sub = EventSubscription(maxsize=maxsize)
        self._subscriptions.append(sub)
        return sub

    async def request(self, cmd: str, params: dict[str, Any] | None = None, *, timeout: float = 30.0) -> Response:
        req_id = str(uuid.uuid4())
        command = Command(id=req_id, type=cmd, params=params or {})
        fut: asyncio.Future[Response] = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut

        await self.channel.send(command.to_dict())
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"Command {cmd} timed out after {timeout}s")

    async def run_prompt(self, message: str) -> RunOutcome:
        # Rule 1: Subscribe before sending prompt
        sub = self.events()
        resp = await self.request("prompt", {"message": message})

        # Rule 2: success: false -> return immediately
        if not resp.success:
            self._subscriptions.remove(sub)
            return RunOutcome(status="error", error=resp.error or "Prompt rejected")

        disposition = resp.data.get("disposition")
        # Rule 3: handled -> finished, do not wait for agent_settled
        if disposition == "handled":
            self._subscriptions.remove(sub)
            return RunOutcome(status="handled")

        # Rules 4 & 5: queued / started -> await agent_settled with watchdog
        start_time = time.time()
        last_event_time = start_time
        active_tools = 0

        try:
            while True:
                # Watchdog check
                timeout_left = min(5.0, (self.timeout_minutes * 60) - (time.time() - start_time))
                if timeout_left <= 0:
                    await self.abort()
                    return RunOutcome(status="timed_out", error="Wall timeout exceeded")

                try:
                    event = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
                except asyncio.TimeoutError:
                    now = time.time()
                    task_id = self._session_spec.task_id if self._session_spec else ""
                    has_pending_q = bool(
                        self.question_router and self.question_router.list_pending_for_task(task_id)
                    )
                    # Watchdog idle timeout is suspended while waiting for coordinator/user dialog
                    if not has_pending_q and active_tools == 0 and (now - last_event_time) > (self.idle_timeout_minutes * 60):
                        await self.abort()
                        return RunOutcome(status="timed_out", error="Idle timeout exceeded")
                    continue

                now = time.time()
                last_event_time = now

                if event.type == "tool_execution_start":
                    active_tools += 1
                elif event.type == "tool_execution_end":
                    active_tools = max(0, active_tools - 1)
                elif event.type == "agent_settled":
                    # Collect final assistant text & session stats
                    summary = ""
                    try:
                        text_resp = await self.request("get_last_assistant_text", timeout=5.0)
                        if text_resp.success:
                            data_d = as_dict(text_resp.data) or {}
                            summary = str(data_d.get("text") or data_d.get("content") or "")
                    except Exception:
                        pass

                    try:
                        stats_resp = await self.request("get_session_stats", timeout=5.0)
                        if stats_resp.success:
                            self._last_stats = parse_pi_stats(as_dict(stats_resp.data) or {})
                    except Exception:
                        pass

                    return RunOutcome(
                        status="succeeded",
                        summary=summary,
                        response=summary,
                        stats=self._last_stats,
                    )

                # Rule 6: Process exited unexpectedly before settled
                if self.channel.proc and self.channel.proc.returncode is not None:
                    return RunOutcome(
                        status="error",
                        error=f"Pi process exited prematurely ({self.channel.proc.returncode})",
                        raw_error_line=self.channel.stderr_tail,
                    )
        finally:
            if sub in self._subscriptions:
                self._subscriptions.remove(sub)

    async def steer(self, message: str) -> None:
        await self.request("steer", {"message": message})

    async def follow_up(self, message: str) -> RunOutcome:
        return await self.run_prompt(message)

    async def abort(self) -> None:
        try:
            await self.request("abort", timeout=3.0)
        except Exception:
            pass
        await self.channel.close(grace=3.0)

    async def close(self) -> None:
        for t in list(self._ui_tasks):
            if not t.done():
                t.cancel()
        task = self._reader_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                cur = asyncio.current_task()
                if cur is not None and hasattr(cur, "cancelling") and cur.cancelling():
                    raise
            except Exception:
                logger.debug("PiClient reader task error on close", exc_info=True)
        await self.channel.close(grace=2.0)
