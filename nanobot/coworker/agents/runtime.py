"""AgentRuntime executing coworker room guests using AgentRunner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from nanobot.agent.hook import AgentHook, AgentHookContext
from nanobot.agent.runner import AgentRunner, AgentRunSpec
from nanobot.agent.tools.context import RequestContext, bind_request_context, reset_request_context
from nanobot.agent.tools.exec_session import ExecSessionManager
from nanobot.config.schema import AgentDefaults
from nanobot.coworker.agents.contract import contract_repair_message, parse_guest_contract
from nanobot.coworker.agents.prompt import build_system_prompt
from nanobot.coworker.agents.thread import AgentThreadStore
from nanobot.coworker.agents.toolset import build_tools
from nanobot.coworker.room.store import rooms_dir
from nanobot.llm_usage.context import current_llm_usage_source
from nanobot.security.workspace_access import (
    bind_workspace_scope,
    default_workspace_scope,
    reset_workspace_scope,
)

if TYPE_CHECKING:
    from nanobot.agent.runner import AgentRunResult
    from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig
    from nanobot.coworker.runtime import CoworkerServices
    from nanobot.security.workspace_access import WorkspaceScope
    from nanobot.utils.llm_runtime import LLMRuntime


_NO_CONTRACT_REPAIR = frozenset({"error", "cancelled", "max_iterations", "empty_final_response"})


@dataclass
class GuestResult:
    text: str
    contract: dict[str, Any] | None = None
    tools_used: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = "end_turn"
    contract_failed: bool = False

    def summary_for_thread(self) -> str:
        """Text summary to record in thread history."""
        if self.contract:
            summary = self.contract.get("summary")
            if isinstance(summary, str) and summary.strip():
                return summary.strip()
        return self.text


def to_guest_result(result: AgentRunResult, agent: RoomAgentConfig) -> GuestResult:
    text = (result.final_content or "").strip()
    tools_used = list(dict.fromkeys(result.tools_used))
    usage_dict: dict[str, int] = {}
    if result.usage:
        usage_dict = {
            "prompt_tokens": result.usage.input_tokens,
            "completion_tokens": result.usage.output_tokens,
            "total_tokens": result.usage.total_tokens,
        }
    return GuestResult(
        text=text,
        contract=None,
        tools_used=tools_used,
        usage=usage_dict,
        stop_reason=result.stop_reason,
    )


async def _skip_guest_history_consolidation(
    _messages: list[dict[str, Any]],
    _previous_summary: str | None,
) -> None:
    """Guest threads persist task/reply summaries; skip runner transcript compaction."""
    return None


class GuestHook(AgentHook):
    """Hook for guest execution — logs tool calls and tracks ActiveGuest progress."""

    def __init__(self, agent_id: str, progress: Any | None = None) -> None:
        super().__init__()
        self.agent_id = agent_id
        self.progress = progress

    async def before_execute_tools(self, context: AgentHookContext) -> None:
        for tool_call in context.tool_calls:
            args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
            logger.debug(
                "Guest [{}] executing: {} with arguments: {}",
                self.agent_id,
                tool_call.name,
                args_str,
            )
        self._update_progress(context)

    async def after_iteration(self, context: AgentHookContext) -> None:
        self._update_progress(context)

    def _update_progress(self, context: AgentHookContext) -> None:
        if self.progress is None:
            return
        self.progress.iteration = context.iteration
        if context.tool_calls:
            self.progress.last_tool = context.tool_calls[-1].name
        elif context.tool_events:
            last = context.tool_events[-1]
            name = last.get("name") or last.get("tool")
            if isinstance(name, str):
                self.progress.last_tool = name


class AgentRuntime:
    """Executes a room guest turn with its own system prompt, isolated toolset, and thread history."""

    def __init__(self, svc: CoworkerServices, cfg: CoworkerConfig) -> None:
        self.svc = svc
        self.cfg = cfg
        self.runner = AgentRunner()

    async def run(
        self,
        agent: RoomAgentConfig,
        task_msg: str,
        *,
        room_id: str,
        session_key: str,
        channel: str,
        chat_id: str,
        project_root: Path,
        runtime: LLMRuntime,
        progress: Any | None = None,
        workspace_scope: WorkspaceScope | None = None,
    ) -> GuestResult:
        from nanobot.coworker.agents.prompt import resolve_home

        restrict_default = bool(self.svc.tools_config and self.svc.tools_config.restrict_to_workspace)
        scope = workspace_scope or default_workspace_scope(project_root, restrict_default)
        project_root = scope.project_path
        thread = AgentThreadStore(self.svc.workspace, agent.id, room_id)
        persist_memory = agent.memory != "none" and resolve_home(agent, self.svc.workspace) is not None
        history = thread.recent(agent.thread_turns) if persist_memory else []
        sys_prompt = build_system_prompt(
            agent,
            project_root=project_root,
            svc=self.svc,
            roster=self.cfg.room.agents,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": sys_prompt},
            *history,
            {"role": "user", "content": task_msg},
        ]
        esm = ExecSessionManager()
        tools = build_tools(
            agent,
            self.svc,
            project_root=project_root,
            exec_session_manager=esm,
            restrict_to_workspace=scope.restrict_to_workspace,
        )
        artifacts_dir = rooms_dir(self.svc.workspace) / room_id / "artifacts" / agent.id
        _grant_artifact_access(tools, artifacts_dir)

        max_tool_chars = (
            self.svc.max_tool_result_chars
            if self.svc.max_tool_result_chars is not None
            else AgentDefaults().max_tool_result_chars
        )

        token = bind_request_context(
            RequestContext(
                channel=channel,
                chat_id=chat_id,
                session_key=session_key,
                runtime=runtime,
            )
        )
        workspace_token = bind_workspace_scope(scope)

        async def _run(initial: list[dict[str, Any]]) -> AgentRunResult:
            return await self.runner.run(
                AgentRunSpec(
                    initial_messages=initial,
                    tools=tools,
                    runtime=runtime,
                    max_iterations=agent.max_iterations,
                    max_tool_result_chars=max_tool_chars,
                    session_key=f"coworker-agent:{agent.id}:{room_id}",
                    workspace=project_root,
                    hook=GuestHook(agent.id, progress),
                    max_iterations_message="Stopped at the iteration limit; report what is done.",
                    finalize_on_max_iterations=True,
                    llm_usage_source=current_llm_usage_source(),
                    consolidate_history=_skip_guest_history_consolidation,
                )
            )

        guest: GuestResult | None = None
        try:
            result = await _run(messages)
            guest = to_guest_result(result, agent)
            if agent.output_contract == "default":
                payload, errors = parse_guest_contract(guest.text)
                can_repair = bool(errors) and guest.stop_reason not in _NO_CONTRACT_REPAIR
                if can_repair:
                    # Prefer the runner transcript (system + tools). Fall back if
                    # a stub result omitted the prompt.
                    repair = list(result.messages)
                    if not repair or repair[0].get("role") != "system":
                        repair = list(messages)
                    if not repair or repair[-1].get("role") != "assistant":
                        repair.append({"role": "assistant", "content": guest.text})
                    repair.append({"role": "user", "content": contract_repair_message(errors)})
                    result2 = await _run(repair)
                    guest2 = to_guest_result(result2, agent)
                    guest2.usage = _merge_usage(guest.usage, guest2.usage)
                    guest2.tools_used = list(dict.fromkeys([*guest.tools_used, *guest2.tools_used]))
                    guest = guest2
                    payload, errors = parse_guest_contract(guest.text)
                guest.contract = payload
                guest.contract_failed = bool(errors)
                if errors:
                    logger.info(
                        "Guest [{}] output contract failed{}: {}",
                        agent.id,
                        " after retry" if can_repair else f" ({guest.stop_reason})",
                        "; ".join(errors),
                    )
        finally:
            reset_workspace_scope(workspace_token)
            reset_request_context(token)
            await esm.close_all()

        if guest is None:
            raise RuntimeError("guest run produced no result")
        if persist_memory:
            thread.append_turn(
                task=task_msg,
                reply=guest.summary_for_thread(),
                tools_used=guest.tools_used,
                usage=guest.usage,
            )
        return guest


def _merge_usage(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
    keys = set(first) | set(second)
    return {key: int(first.get(key, 0)) + int(second.get(key, 0)) for key in keys}


def _grant_artifact_access(tools: Any, artifacts: Path) -> None:
    """Let restricted guests write/read the room artifact directory (may sit outside project_root)."""
    names = getattr(tools, "tool_names", None)
    getter = getattr(tools, "get", None)
    if not isinstance(names, (list, tuple)) or not callable(getter):
        return
    artifacts.mkdir(parents=True, exist_ok=True)
    for name in names:
        if not isinstance(name, str):
            continue
        tool = getter(name)
        if tool is None:
            continue
        writes = getattr(tool, "_extra_write_allowed_dirs", None)
        if isinstance(writes, list):
            writes.append(artifacts)
        reads = getattr(tool, "_extra_read_allowed_dirs", None)
        if isinstance(reads, list):
            reads.append(artifacts)
