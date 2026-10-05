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
from nanobot.coworker.agents.prompt import build_system_prompt
from nanobot.coworker.agents.thread import AgentThreadStore
from nanobot.coworker.agents.toolset import build_tools
from nanobot.llm_usage.context import current_llm_usage_source

if TYPE_CHECKING:
    from nanobot.agent.runner import AgentRunResult
    from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig
    from nanobot.coworker.runtime import CoworkerServices
    from nanobot.utils.llm_runtime import LLMRuntime


@dataclass
class GuestResult:
    text: str
    contract: dict[str, Any] | None = None
    tools_used: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = "end_turn"

    def summary_for_thread(self) -> str:
        """Text summary to record in thread history."""
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
    ) -> GuestResult:
        from nanobot.coworker.agents.prompt import resolve_home

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
        tools = build_tools(agent, self.svc, project_root=project_root, exec_session_manager=esm)

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
        try:
            result = await self.runner.run(
                AgentRunSpec(
                    initial_messages=messages,
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
                    # TODO(phase-2 follow-up): wire consolidate_history for long guest runs.
                )
            )
        finally:
            reset_request_context(token)
            await esm.close_all()

        guest = to_guest_result(result, agent)
        if persist_memory:
            thread.append_turn(
                task=task_msg,
                reply=guest.summary_for_thread(),
                tools_used=guest.tools_used,
                usage=guest.usage,
            )
        return guest
