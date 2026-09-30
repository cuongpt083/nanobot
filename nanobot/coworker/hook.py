"""Per-turn hook wiring every coworker feature into the runner lifecycle.

- ``before_run``: genuine user turns arm rooms on @mentions and reset budgets.
- ``before_iteration``: publish the live message list for the advisor/distill tools.
- ``transform_request``: cache-aware payload optimization, feature directives,
  per-session tool visibility, keep-alive capture.
- ``after_run``: drive workflows, launch room teammates, nudge an advisor review.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.agent.hook import (
    AgentHook,
    AgentHookContext,
    AgentRunHookContext,
    AgentTurnHookContext,
)
from nanobot.agent.tools.context import current_request_context
from nanobot.coworker import directives
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import NON_EVIDENCE_TOOLS, breaker_open_seconds
from nanobot.coworker.advisor.tool import ADVISOR_TOOL
from nanobot.coworker.coding.tools import CODING_TOOL
from nanobot.coworker.config import CoworkerConfig, load_coworker_config
from nanobot.coworker.context import keepalive, optimizer
from nanobot.coworker.context.tools import WASTED_TOOL, wasted_ids
from nanobot.coworker.room import scheduler
from nanobot.coworker.room.tools import ROOM_TOOLS, room_armed_for
from nanobot.coworker.runtime import (
    forget_live_messages,
    get_session,
    inject_turn,
    is_automated_turn,
    mark_turn_finished,
    mark_turn_running,
    post_to_chat,
    remember_live_messages,
    services,
    turn_kind,
)
from nanobot.coworker.transcript import as_dict, as_list, content_text, is_auto_turn
from nanobot.coworker.workflows import drive
from nanobot.coworker.workflows.registry import list_workflows
from nanobot.coworker.workflows.tools import WORKFLOW_TOOLS

ADVISOR_REVIEW_MARKER = "[auto-advisor-review]"
KIND_ADVISOR_REVIEW = "advisor_review"
KIND_CODING_RESULT = "coding_result"
# Injected turns that still deserve an advisor nudge (the executor just received work to vet).
_NUDGE_KINDS = frozenset({KIND_CODING_RESULT})
_READ_ONLY_TOOLS = frozenset({
    "read_file", "list_dir", "glob", "grep", "search", "web_search", "web_fetch", "sessions_list",
    "session_messages", "cron",
})
_workflow_index_cache: tuple[float, bool] = (0.0, False)


def _has_workflows() -> bool:
    global _workflow_index_cache
    now = time.monotonic()
    if now - _workflow_index_cache[0] < 30:
        return _workflow_index_cache[1]
    svc = services()
    present = bool(svc and list_workflows(svc.workspace))
    _workflow_index_cache = (now, present)
    return present


def _append_system(messages: list[dict[str, Any]], sections: list[str]) -> list[dict[str, Any]]:
    if not sections or not messages or messages[0].get("role") != "system":
        return messages
    extra = "\n\n" + "\n\n".join(sections)
    head: dict[str, Any] = messages[0]
    content: object = head.get("content")
    blocks = as_list(content)
    if isinstance(content, str):
        head = {**head, "content": content + extra}
    elif blocks is not None:
        head = {**head, "content": [*blocks, {"type": "text", "text": extra.lstrip()}]}
    else:
        return messages
    return [head, *messages[1:]]


def _tool_name(definition: dict[str, Any]) -> str:
    fn = as_dict(definition.get("function"))
    return str(fn.get("name")) if fn is not None else str(definition.get("name") or "")


class CoworkerHook(AgentHook):
    def __init__(self, turn: AgentTurnHookContext) -> None:
        super().__init__()
        self._turn = turn
        self._key = turn.session_key
        self._kind = turn_kind(turn.metadata)
        self._genuine_text: str | None = None

    # ---------- lifecycle ----------

    def _is_genuine_candidate(self) -> bool:
        meta = self._turn.metadata
        return (
            self._kind is None
            and not meta.get("injected_event")
            and not meta.get("_internal_continuation")
            and not is_automated_turn(meta, self._key)
        )

    async def before_run(self, context: AgentRunHookContext) -> None:
        mark_turn_running(self._key)
        if not self._is_genuine_candidate():
            return
        last_user = next((m for m in reversed(context.messages) if m.get("role") == "user"), None)
        text = content_text(last_user.get("content")) if last_user else ""
        if not text.strip() or is_auto_turn(text):
            return
        self._genuine_text = text
        session = get_session(self._key)
        if session is None or not self._key:
            return
        scheduler.reset_chain_budget(self._key)
        if not scheduler.is_armed(session) and scheduler.mentioned_agents(text):
            scheduler.set_armed(session, True)
            logger.info("coworker: room armed for {} by @mention", self._key)

    async def before_iteration(self, context: AgentHookContext) -> None:
        remember_live_messages(self._key, context.messages)

    async def on_finally(self, context: AgentRunHookContext) -> None:
        forget_live_messages(self._key)
        mark_turn_finished(self._key)

    # ---------- payload ----------

    def transform_request(
        self,
        context: AgentHookContext,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        stateful: bool,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        if not self._key or services() is None:
            return messages, tools
        cfg = load_coworker_config()
        session = get_session(self._key)
        if session is None:
            return messages, tools
        ctx_cfg = cfg.context
        ttl = optimizer.cache_ttl_seconds(ctx_cfg.cache_ttl_seconds)
        if not stateful:
            messages = optimizer.optimize_payload(
                self._key,
                messages,
                optimizer.OptimizePolicy(
                    trim_enabled=ctx_cfg.trim.enabled,
                    max_turns=ctx_cfg.trim.max_turns,
                    optimize=ctx_cfg.optimize,
                    freeze_system=ctx_cfg.freeze_system_prompt,
                    freeze_max_hold_s=ctx_cfg.freeze_max_hold_minutes * 60,
                    ttl_s=ttl,
                    wasted_ids=wasted_ids(session) if ctx_cfg.optimize else frozenset(),
                ),
            )

        advisor_on = advisor_state.effective(session) is not None
        room_on = room_armed_for(session)
        workflows_on = cfg.workflows.enabled
        coding_on = cfg.coding.enabled
        sections: list[str] = []
        if advisor_on:
            sections.append(directives.ADVISOR)
        if room_on:
            sections += [directives.room_owner(cfg.room.agents), directives.ROOM_STATE]
        if workflows_on and _has_workflows():
            sections.append(directives.WORKFLOWS)
        if ctx_cfg.optimize:
            sections.append(directives.WASTED)
        if coding_on:
            sections.append(directives.CODING)
        messages = _append_system(messages, sections)

        hidden: set[str] = set()
        if not advisor_on:
            hidden.add(ADVISOR_TOOL)
        if not room_on:
            hidden |= ROOM_TOOLS
        if not workflows_on:
            hidden |= WORKFLOW_TOOLS
        if not ctx_cfg.optimize:
            hidden.add(WASTED_TOOL)
        if not coding_on:
            hidden.add(CODING_TOOL)
        if tools and hidden:
            tools = [t for t in tools if _tool_name(t) not in hidden]

        if ctx_cfg.keepalive.enabled and not stateful:
            request = current_request_context()
            if request is not None and request.runtime is not None:
                keepalive.capture(
                    self._key,
                    runtime=request.runtime,
                    messages=messages,
                    tools=tools,
                    ttl_s=ttl,
                    window_s=ctx_cfg.keepalive.window_minutes * 60,
                    max_pings=ctx_cfg.keepalive.max_pings,
                    lead_s=ctx_cfg.keepalive.lead_seconds,
                )
        return messages, tools

    # ---------- after the run ----------

    async def after_run(self, context: AgentRunHookContext) -> None:
        forget_live_messages(self._key)
        svc = services()
        key = self._key
        if svc is None or not key or context.stop_reason in ("cancelled", "error"):
            return
        session = get_session(key)
        if session is None:
            return
        cfg = load_coworker_config()
        if await self._drive_workflow(key, session, context, svc.workspace):
            return
        if room_armed_for(session) and scheduler.maybe_start_room_run(
            key, channel=self._turn.channel, chat_id=self._turn.chat_id
        ):
            return
        await self._maybe_nudge_advisor(key, session, context, cfg)

    async def _drive_workflow(
        self, key: str, session: Any, context: AgentRunHookContext, workspace: Path
    ) -> bool:
        meta = self._turn.metadata
        step_turn = None
        if self._kind == drive.KIND_WORKFLOW_STEP:
            step_turn = (str(meta.get("workflow_run", "")), str(meta.get("workflow_step", "")))
        try:
            injection, note = drive.on_turn_end(
                session,
                workspace,
                final_content=context.final_content,
                step_turn=step_turn,
                genuine_user_text=self._genuine_text,
            )
        except Exception:
            logger.exception("coworker: workflow drive failed for {}", self._key)
            return False
        if note:
            await post_to_chat(channel=self._turn.channel, chat_id=self._turn.chat_id, content=note)
        if injection is None:
            return step_turn is not None
        await inject_turn(
            session_key=key,
            channel=self._turn.channel,
            chat_id=self._turn.chat_id,
            content=injection.content,
            kind=drive.KIND_WORKFLOW_STEP,
            extra={"workflow_run": injection.run_id, "workflow_step": injection.step},
        )
        return True

    async def _maybe_nudge_advisor(
        self, key: str, session: Any, context: AgentRunHookContext, cfg: CoworkerConfig
    ) -> None:
        if not cfg.advisor.review_nudge:
            return
        result_turn = self._kind in _NUDGE_KINDS
        if self._kind is not None and not result_turn:
            return
        if not result_turn and self._genuine_text is None:
            return
        if context.stop_reason not in ("completed", None):
            return
        eff = advisor_state.effective(session)
        if eff is None or eff.uses >= eff.max_uses:
            return
        consulted = False
        gap = 0
        for name in context.tools_used:
            if name == ADVISOR_TOOL:
                consulted, gap = True, 0
            elif name not in NON_EVIDENCE_TOOLS and name not in _READ_ONLY_TOOLS:
                gap += 1
        if result_turn:
            # The executor just received a finished coding task: a review is due unless it already asked.
            if consulted:
                return
        else:
            threshold = cfg.advisor.reconsult_gap if consulted else cfg.advisor.first_consult_gap
            if gap < threshold:
                return
        try:
            from nanobot.coworker.runtime import runtime_for_preset

            model_key = runtime_for_preset(eff.preset).model
        except Exception:
            return
        if breaker_open_seconds(model_key) > 0:
            logger.warning("coworker: advisor review nudge skipped, circuit open for {}", model_key)
            return
        if result_turn:
            text = (
                f"{ADVISOR_REVIEW_MARKER} A coding task finished and you have not consulted the advisor on it. "
                "Read the real changes first (coding_agent action=\"diff\" with the task id), then call "
                "advisor(focus=\"review this diff and the acceptance result before I recommend a merge\"). "
                "If it flags a real problem, steer or resume the task; otherwise report to the user."
            )
        else:
            text = (
                f"{ADVISOR_REVIEW_MARKER} You have done a lot of work ({gap} steps) since your last advisor consult. "
                if consulted
                else f"{ADVISOR_REVIEW_MARKER} You did substantive work this run without consulting the advisor. "
            ) + (
                "Call advisor() NOW for a review — it sees your full transcript including everything you just did. "
                "If it flags a real problem, fix it before finishing; otherwise briefly confirm completion."
            )
        logger.info("coworker: advisor review nudge for {} (gap={}, consulted={})", self._key, gap, consulted)
        await inject_turn(
            session_key=key,
            channel=self._turn.channel,
            chat_id=self._turn.chat_id,
            content=text,
            kind=KIND_ADVISOR_REVIEW,
        )


def create_coworker_hook(turn: AgentTurnHookContext) -> AgentHook | None:
    if turn.ephemeral or not turn.session_key:
        return None
    return CoworkerHook(turn)
