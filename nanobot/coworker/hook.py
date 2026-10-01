"""Per-turn hook wiring every coworker feature into the runner lifecycle.

- ``before_run``: genuine user turns arm rooms on @mentions and reset budgets.
- ``before_iteration``: publish the live message list for the advisor/distill tools.
- ``transform_request``: cache-aware payload optimization, feature directives,
  per-session tool visibility, keep-alive capture.
- ``after_run``: drive workflows, launch room teammates, nudge an advisor review.
"""

from __future__ import annotations

import time
from dataclasses import replace
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
from nanobot.coworker.advisor import policy
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import breaker_open_seconds
from nanobot.coworker.advisor.stuck import StuckTracker, failure_signature
from nanobot.coworker.advisor.tool import ADVISOR_TOOL
from nanobot.coworker.coding.tools import CODING_TOOL
from nanobot.coworker.config import CoworkerConfig, load_coworker_config
from nanobot.coworker.context import cache_policy, keepalive, keepalive_state, metrics, optimizer
from nanobot.coworker.context.tools import WASTED_TOOL, wasted_ids
from nanobot.coworker.persona import resolve_persona
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
    runtime_for_preset,
    services,
    session_state,
    turn_kind,
)
from nanobot.coworker.transcript import as_dict, as_list, content_text, is_auto_turn
from nanobot.coworker.workflows import drive
from nanobot.coworker.workflows.registry import list_workflows
from nanobot.coworker.workflows.tools import WORKFLOW_TOOLS
from nanobot.providers.base import ProviderCallContext, ToolCallRequest

KIND_CODING_RESULT = "coding_result"
_workflow_index_cache: tuple[float, bool] = (0.0, False)


def _max_tool_iterations() -> int:
    """The configured per-turn iteration ceiling (D11: leave room for a review turn)."""
    from nanobot.config.loader import load_config

    try:
        return int(load_config().agents.defaults.max_tool_iterations)
    except Exception:
        return 200


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


_CODING_BACKENDS = ("pi", "agy")
ADVISOR_MENTION = "advisor"


def _with_note(message: dict[str, Any], note: str) -> dict[str, Any] | None:
    content: object = message.get("content")
    blocks = as_list(content)
    if isinstance(content, str):
        return {**message, "content": f"{content}\n\n{note}"}
    if blocks is not None:
        return {**message, "content": [*blocks, {"type": "text", "text": note}]}
    return None


def _annotate_mentions(
    messages: list[dict[str, Any]], cfg: CoworkerConfig, *, advisor_on: bool
) -> list[dict[str, Any]]:
    """Tell the model when a user message addresses ``@agy`` / ``@pi`` / ``@advisor``.

    Derived from each message's own text, so a given message always gets the same bytes and the
    cached prefix of earlier turns is never disturbed.
    """
    room_ids = {a.id for a in cfg.room.agents}  # room teammates are routed by the room scheduler
    out: list[dict[str, Any]] | None = None
    for i, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        text = content_text(message.get("content"))
        if not text or "@" not in text or is_auto_turn(text):
            continue
        notes: list[str] = []
        for name in scheduler.mention_ids(text):
            if name in room_ids:
                continue
            if name in _CODING_BACKENDS:
                notes.append(directives.coding_mention_note(name, enabled=cfg.coding.enabled))
            elif name == ADVISOR_MENTION:
                notes.append(directives.advisor_mention_note(enabled=advisor_on))
        if not notes:
            continue
        annotated = _with_note(message, "\n".join(notes))
        if annotated is None:
            continue
        if out is None:
            out = list(messages)
        out[i] = annotated
    return out if out is not None else messages


_STUCK_HINT = "same failure as an earlier attempt"


def _annotate_stuck(
    messages: list[dict[str, Any]], stuck: frozenset[str]
) -> list[dict[str, Any]]:
    if not stuck:
        return messages
    out: list[dict[str, Any]] | None = None
    note = (
        "[nanobot: same failure as an earlier attempt — "
        'call advisor(focus="<what failed and what you tried>") before another fix attempt.]'
    )
    for i, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        call_id = str(message.get("tool_call_id") or "")
        if call_id not in stuck:
            continue
        content = message.get("content")
        if isinstance(content, str):
            if _STUCK_HINT in content:
                continue
            annotated = {**message, "content": f"{content}\n\n{note}"}
        elif isinstance(content, list):
            if any(_STUCK_HINT in str(b.get("text", "")) for b in content if isinstance(b, dict)):
                continue
            annotated = {**message, "content": [*content, {"type": "text", "text": note}]}
        else:
            continue
        if out is None:
            out = list(messages)
        out[i] = annotated
    return out if out is not None else messages


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
        self._iter_ctx: AgentHookContext | None = None
        self._nudged = False
        self._last_runtime: Any | None = None
        self._stuck = StuckTracker()

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
        # A user who wrote @advisor wants the consult now; skip the thin-context refusal for it.
        if ADVISOR_MENTION in scheduler.mention_ids(text):
            advisor_state.mark_user_request(session)
        else:
            advisor_state.clear_user_request(session)
        scheduler.reset_chain_budget(self._key)
        if not scheduler.is_armed(session) and scheduler.mentioned_agents(text):
            scheduler.set_armed(session, True)
            logger.info("coworker: room armed for {} by @mention", self._key)

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._iter_ctx = context
        remember_live_messages(self._key, context.messages)

    def _record_tool_result(self, tool_call: ToolCallRequest, params: Any, result: Any) -> None:
        if tool_call.name == "advisor":
            self._stuck.reset()
            return
        if not self._key:
            return
        session = get_session(self._key)
        if session is None:
            return
        eff = advisor_state.effective(session)
        if (
            eff is None
            or eff.mode != advisor_state.MODE_CODING
            or eff.uses >= eff.max_uses
            or not load_coworker_config().advisor.stuck_detection
        ):
            return
        args = (
            params
            if isinstance(params, dict)
            else (tool_call.arguments if isinstance(tool_call.arguments, dict) else {})
        )
        sig = failure_signature(tool_call.name, args, result)
        if self._stuck.record(sig):
            advisor_state.add_stuck_id(session, tool_call.id)

    async def after_execute_tool(
        self,
        context: AgentHookContext,
        tool_call: ToolCallRequest,
        tool: Any,
        params: Any,
        result: Any,
    ) -> None:
        self._record_tool_result(tool_call, params, result)

    async def on_execute_tool_error(
        self,
        context: AgentHookContext,
        tool_call: ToolCallRequest,
        tool: Any,
        params: Any,
        error: Any,
    ) -> None:
        self._record_tool_result(tool_call, params, error)

    async def after_iteration(self, context: AgentHookContext) -> None:
        metrics.record(self._key, context.usage)
        keepalive.mark_in_flight(self._key, False)
        if self._key:
            session = get_session(self._key)
            if session is not None:
                state = session_state(session)
                request = current_request_context()
                runtime = request.runtime if request else self._last_runtime
                provider = runtime.provider if runtime else None
                provider_name = getattr(provider, "provider_name", "") if provider else ""
                model = runtime.model if runtime else ""
                kw_setting = keepalive_state.effective(session)
                ttl1h_armed = (
                    kw_setting.enabled
                    and kw_setting.strategy == "ttl1h"
                    and cache_policy.supports_ttl1h(provider)
                )
                keepalive.mark_real_turn(self._key, ttl1h_armed=ttl1h_armed)
                state["cache"] = {
                    "last_llm_call_at": time.time(),
                    "provider": provider_name,
                    "model": model,
                    "ttl1h_armed": ttl1h_armed,
                }

    async def on_finally(self, context: AgentRunHookContext) -> None:
        forget_live_messages(self._key)
        mark_turn_finished(self._key)
        keepalive.mark_in_flight(self._key, False)

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
        keepalive.mark_in_flight(self._key, True)
        kw_setting = keepalive_state.effective(session)
        request = current_request_context()
        runtime = request.runtime if request else None
        self._last_runtime = runtime

        policy = None
        if runtime is not None:
            policy = cache_policy.resolve(
                runtime.provider,
                runtime.model,
                retention="long" if kw_setting.strategy == "ttl1h" else "short",
                ttl_override=ctx_cfg.cache_ttl_seconds,
            )
        ttl = policy.ttl_s if policy else optimizer.cache_ttl_seconds(ctx_cfg.cache_ttl_seconds)

        now_ts = time.time()
        opt_state = optimizer.state_for(self._key)
        cold = opt_state.last_send == 0.0 or (now_ts - opt_state.last_send > ttl)
        latch, _, _ = optimizer.resolve_latched(
            session,
            cold=cold,
            cfg_optimize=ctx_cfg.optimize,
            cfg_trim=ctx_cfg.trim.enabled,
        )

        if not stateful:
            messages = optimizer.optimize_payload(
                self._key,
                messages,
                optimizer.OptimizePolicy(
                    trim_enabled=latch.trim,
                    max_turns=ctx_cfg.trim.max_turns,
                    optimize=latch.optimize,
                    freeze_system=ctx_cfg.freeze_system_prompt,
                    freeze_max_hold_s=ctx_cfg.freeze_max_hold_minutes * 60,
                    ttl_s=ttl,
                    wasted_ids=wasted_ids(session) if latch.optimize else frozenset(),
                ),
                now=now_ts,
            )

        advisor_eff = advisor_state.effective(session)
        advisor_on = advisor_eff is not None
        room_on = room_armed_for(session)
        workflows_on = cfg.workflows.enabled
        coding_on = cfg.coding.enabled
        persona_agent = resolve_persona(session, cfg)
        sections: list[str] = []
        if persona_agent is not None:
            sections.append(directives.persona_section(persona_agent))
        if advisor_eff is not None:
            brainstorm = advisor_eff.mode == advisor_state.MODE_BRAINSTORM
            sections.append(directives.ADVISOR_BRAINSTORM if brainstorm else directives.ADVISOR)
        if room_on:
            sections += [directives.room_owner(cfg.room.agents), directives.ROOM_STATE]
        if workflows_on and _has_workflows():
            sections.append(directives.WORKFLOWS)
        if latch.optimize:
            sections.append(directives.WASTED)
        if coding_on:
            sections.append(directives.CODING)
        messages = _append_system(messages, sections)
        messages = _annotate_mentions(messages, cfg, advisor_on=advisor_on)
        if advisor_on:
            messages = _annotate_stuck(messages, advisor_state.stuck_ids(session))

        hidden: set[str] = set()
        if not advisor_on:
            hidden.add(ADVISOR_TOOL)
        if not room_on:
            hidden |= ROOM_TOOLS
        if not workflows_on:
            hidden |= WORKFLOW_TOOLS
        if not latch.optimize:
            hidden.add(WASTED_TOOL)
        if not coding_on:
            hidden.add(CODING_TOOL)
        if tools and hidden:
            tools = [t for t in tools if _tool_name(t) not in hidden]

        if kw_setting.enabled and not stateful and runtime is not None:
            keepalive.capture(
                self._key,
                runtime=runtime,
                messages=messages,
                tools=tools,
                ttl_s=ttl,
                window_s=kw_setting.window_min * 60,
                max_pings=policy.ping_cap if policy else ctx_cfg.keepalive.max_pings,
                lead_s=policy.lead_s if policy else ctx_cfg.keepalive.lead_seconds,
            )
        return messages, tools

    def adjust_provider_context(
        self,
        context: AgentHookContext,
        provider_context: ProviderCallContext,
    ) -> ProviderCallContext:
        if not self._key:
            return provider_context
        session = get_session(self._key)
        if session is None:
            return provider_context
        kw_setting = keepalive_state.effective(session)
        request = current_request_context()
        runtime = request.runtime if request else self._last_runtime
        provider = runtime.provider if runtime else None
        if kw_setting.enabled and kw_setting.strategy == "ttl1h" and cache_policy.supports_ttl1h(provider):
            return replace(provider_context, cache_retention="long")
        return provider_context

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
        if await self._drive_workflow(key, session, context, svc.workspace):
            return
        if room_armed_for(session) and scheduler.maybe_start_room_run(
            key, channel=self._turn.channel, chat_id=self._turn.chat_id
        ):
            return

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

    def continuation(self) -> str | None:
        """In-run advisor review nudge (D1).

        Returned to the runner, which appends it inside the *same* run only when no user
        message is waiting, so a real user turn always wins. Latched once per run.
        """
        if self._nudged or not self._key:
            return None
        cfg = load_coworker_config()
        if not cfg.advisor.review_nudge:
            return None
        result_turn = self._kind == KIND_CODING_RESULT
        if self._kind is not None and not result_turn:
            return None
        if not result_turn and self._genuine_text is None:
            return None
        if is_automated_turn(self._turn.metadata, self._key):
            return None
        context = self._iter_ctx
        if context is not None and context.iteration >= _max_tool_iterations() - 2:
            return None  # D11: leave room for the review turn under the iteration ceiling
        session = get_session(self._key)
        if session is None:
            return None
        eff = advisor_state.effective(session)
        if eff is None or eff.uses >= eff.max_uses:
            return None
        try:
            model_key = runtime_for_preset(eff.preset).model
        except Exception:
            return None
        if breaker_open_seconds(model_key) > 0:
            logger.warning("coworker: advisor review nudge skipped, circuit open for {}", model_key)
            return None
        scan = policy.scan_run(context.messages if context is not None else [])
        decision: policy.NudgeDecision | None = None
        if eff.mode != advisor_state.MODE_BRAINSTORM:
            decision = policy.decide_review_nudge(
                scan,
                first_gap=cfg.advisor.first_consult_gap,
                reconsult_gap=cfg.advisor.reconsult_gap,
                coding_result=result_turn,
            )
        if decision is None:
            draft_chars = len(
                (self._iter_ctx.response.content if self._iter_ctx and self._iter_ctx.response else "") or ""
            )
            decision = policy.decide_discussion_gate(
                scan,
                draft_chars=draft_chars,
                mode=eff.mode,
                gate=cfg.advisor.discussion_gate,
                min_chars=cfg.advisor.discussion_min_chars,
                first_gap=cfg.advisor.first_consult_gap,
            )
        if decision is None:
            return None
        self._nudged = True
        advisor_state.record_review_nudge(session, kind=decision.kind, now=time.time())
        logger.info(
            "coworker: in-run advisor review nudge for {} (kind={}, gap={})",
            self._key, decision.kind, decision.gap,
        )
        return policy.review_nudge_text(decision)


def create_coworker_hook(turn: AgentTurnHookContext) -> AgentHook | None:
    if turn.ephemeral or not turn.session_key:
        return None
    return CoworkerHook(turn)
