"""Per-turn hook wiring every coworker feature into the runner lifecycle.

- ``before_run``: genuine user turns arm rooms on @mentions and reset budgets.
- ``before_iteration``: publish the live message list for the advisor/distill tools.
- ``transform_request``: cache-aware payload optimization, feature directives,
  per-session tool visibility, keep-alive capture.
- ``after_run``: drive workflows, launch room teammates, nudge an advisor review.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from loguru import logger

from nanobot.agent.hook import (
    AgentHook,
    AgentHookContext,
    AgentRunHookContext,
    AgentTurnHookContext,
)
from nanobot.agent.tools.context import current_request_context
from nanobot.coworker import directives, metrics_store
from nanobot.coworker.advisor import ledger as advisor_ledger
from nanobot.coworker.advisor import policy
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.checkpoint import hits as checkpoint_hits
from nanobot.coworker.advisor.checkpoint import parse_checkpoint
from nanobot.coworker.advisor.consult import TOOL_RESULT_MAX_CHARS, breaker_open_seconds
from nanobot.coworker.advisor.evidence import WRITE_TOOLS, git_summary, params_paths
from nanobot.coworker.advisor.stuck import StuckTracker, failure_signature
from nanobot.coworker.advisor.tool import ADVISOR_TOOL, project_root_for
from nanobot.coworker.coding.tools import CODING_TOOL
from nanobot.coworker.config import CoworkerConfig, load_coworker_config
from nanobot.coworker.context import cache_policy, keepalive, keepalive_state, metrics, optimizer
from nanobot.coworker.context.tools import WASTED_TOOL, wasted_ids
from nanobot.coworker.persona import get_persona_id, resolve_persona
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
from nanobot.coworker.staged.guard import block_message, blocked_paths
from nanobot.coworker.staged.tools import STAGED_TOOL
from nanobot.coworker.transcript import as_dict, as_list, content_text, is_auto_turn
from nanobot.coworker.workflows import drive
from nanobot.coworker.workflows.registry import list_workflows
from nanobot.coworker.workflows.tools import WORKFLOW_TOOLS
from nanobot.llm_usage.context import current_llm_usage_source
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


_CODING_BACKENDS = ("pi",)
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
    """Tell the model when a user message addresses ``@pi`` / ``@advisor``.

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
            blocks = cast("list[Any]", content)
            if any(
                _STUCK_HINT in str(cast("dict[str, Any]", b).get("text", ""))
                for b in blocks
                if isinstance(b, dict)
            ):
                continue
            annotated: dict[str, Any] = {
                **message,
                "content": [*blocks, {"type": "text", "text": note}],
            }
        else:
            continue
        if out is None:
            out = list(messages)
        out[i] = annotated
    return out if out is not None else messages


NOTE_PREFIX = "[nanobot-advisor]"


def _annotate_notes(
    messages: list[dict[str, Any]], notes: dict[str, str]
) -> list[dict[str, Any]]:
    """Append each stored advisor/harness note to its tool result (stable bytes, idempotent)."""
    if not notes:
        return messages
    out: list[dict[str, Any]] | None = None
    for i, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        note = notes.get(str(message.get("tool_call_id") or ""))
        if not note:
            continue
        content = message.get("content")
        if isinstance(content, str):
            if note in content:
                continue
            annotated: dict[str, Any] = {**message, "content": f"{content}\n\n{note}"}
        elif isinstance(content, list):
            blocks = cast("list[Any]", content)
            if any(
                note in str(cast("dict[str, Any]", b).get("text", ""))
                for b in blocks
                if isinstance(b, dict)
            ):
                continue
            annotated = {**message, "content": [*blocks, {"type": "text", "text": note}]}
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
        # Steering counters since the advisor was last consulted (seeded in before_run).
        self._gap = 0
        self._files: set[str] = set()
        self._written = 0
        self._consulted = False
        self._reviewed_since_write = True  # nothing written yet = nothing to review
        self._c1_fired = False
        self._c3_fired = False
        self._gated = False  # done-gate continuation already issued this run
        self._gated_at_write = -1  # commit gate already blocked once for this write count
        self._consulted_this_turn = False  # a successful advisor consult ran in this turn (room review)

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
        scan = policy.scan_run(context.messages)
        self._gap, self._files = scan.gap, set(scan.files)
        self._written, self._consulted = scan.written_total, scan.consulted
        reviewed = policy.consult_after_last_write(context.messages)
        self._reviewed_since_write = True if reviewed is None else reviewed
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
        mentioned = scheduler.mentioned_agents(text)
        persona_id = get_persona_id(session)
        if persona_id:
            mentioned = [a for a in mentioned if a.lower() != persona_id.lower()]
        if not scheduler.is_armed(session) and mentioned:
            scheduler.set_armed(session, True)
            logger.info("coworker: room armed for {} by @mention", self._key)

    async def before_iteration(self, context: AgentHookContext) -> None:
        self._iter_ctx = context
        remember_live_messages(self._key, context.messages)

    @staticmethod
    def _record_tool_size(tool_call: ToolCallRequest, result: Any) -> None:
        """Content-free size of every tool result entering the context (steering baseline)."""
        text = getattr(result, "content", result)
        chars = len(text) if isinstance(text, str) else len(str(text or ""))
        metrics_store.record_tool_result(
            tool=tool_call.name,
            result_chars=chars,
            elided=chars > TOOL_RESULT_MAX_CHARS,
            is_error=isinstance(result, BaseException)
            or getattr(result, "is_error", False) is True,
        )

    # ---------- steering ----------

    def _steering_eligible(self) -> bool:
        """Only genuine user runs (and finished coding results) are steered, never automated turns."""
        if is_automated_turn(self._turn.metadata, self._key):
            return False
        return self._kind == KIND_CODING_RESULT or (self._kind is None and self._genuine_text is not None)

    def _executor_model(self) -> str | None:
        request = current_request_context()
        runtime = request.runtime if request else self._last_runtime
        return getattr(runtime, "model", None) if runtime else None

    @staticmethod
    def _advisor_usable(eff: advisor_state.AdvisorEffective) -> bool:
        """Budget left and the advisor model not tripped by the circuit breaker."""
        if eff.uses >= eff.max_uses:
            return False
        try:
            return breaker_open_seconds(runtime_for_preset(eff.preset).model) <= 0
        except Exception:
            return False

    def _steer(
        self,
        tool_call: ToolCallRequest,
        params: Any,
        result: Any,
        session: Any,
        eff: advisor_state.AdvisorEffective,
    ) -> None:
        """Mid-run checkpoints (C1/C3), the advisor's own checkpoint (B4) and stop reminder (B3)."""
        cfg = load_coworker_config().advisor
        name = tool_call.name
        if name == ADVISOR_TOOL:
            text = getattr(result, "content", result)
            self._gap, self._c1_fired = 0, False
            self._files.clear()
            self._consulted = True
            if isinstance(text, str) and text.lstrip().startswith("ADVISOR ("):
                self._reviewed_since_write = True
                self._consulted_this_turn = True
            return
        if not self._steering_eligible():
            return
        is_work = policy.is_work_tool(name)
        if is_work:
            self._gap += 1
            advisor_state.count_work_step(session)
        typed_args = as_dict(params) or as_dict(tool_call.arguments) or {}
        paths = params_paths(name, typed_args)
        is_write = name in WRITE_TOOLS
        if is_write:
            self._files.update(paths)
            self._written += 1
            self._reviewed_since_write = False
        if eff.mode != advisor_state.MODE_CODING or not (cfg.ledger or cfg.mid_run_checkpoints):
            return
        ledger = advisor_state.ledger(session) if cfg.ledger else None
        notes: list[str] = []
        if ledger is not None and is_write and ledger.get("verdict") == "stop":
            blockers = (ledger.get("must_fix") or ["see the advisor ledger"])[0]
            notes.append(f"advisor verdict is STOP ({blockers}) — resolve it or consult again before more writes")
        checkpoint = parse_checkpoint(ledger.get("next_checkpoint")) if ledger else None
        command = str(typed_args.get("command") or typed_args.get("cmd") or "")
        if (
            checkpoint is not None
            and not advisor_state.checkpoint_fired(session)
            and checkpoint_hits(checkpoint, tool=name, paths=paths, command=command)
        ):
            advisor_state.mark_checkpoint_fired(session)
            notes.append(
                f"the advisor asked to be consulted at this point ({ledger.get('next_checkpoint') if ledger else ''}) "
                "— call advisor() now"
            )
        if cfg.mid_run_checkpoints and self._advisor_usable(eff):
            pol = policy.resolve_policy(
                cfg, self._executor_model(), steps_override=checkpoint.steps if checkpoint else None
            )
            if is_write and not self._consulted and not self._c3_fired:
                self._c3_fired = True
                notes.append(
                    "first file write of this run with no successful advisor consult yet — consult before "
                    "going further (the advisor's plan is the checkpoint, not a difficulty judgment)"
                )
            if not self._c1_fired and (
                self._gap >= pol.reconsult_gap or len(self._files) >= pol.checkpoint_files
            ):
                self._c1_fired = True
                notes.append(
                    f"{self._gap} work steps and {len(self._files)} files written since your last advisor "
                    "consult — call advisor() now"
                )
        if notes:
            advisor_state.add_result_note(session, tool_call.id, f"{NOTE_PREFIX} " + "; ".join(notes) + ".")

    def _record_tool_result(self, tool_call: ToolCallRequest, params: Any, result: Any) -> None:
        self._record_tool_size(tool_call, result)
        if tool_call.name == "advisor":
            self._stuck.reset()
        if not self._key:
            return
        session = get_session(self._key)
        if session is None:
            return
        eff = advisor_state.effective(session)
        if eff is not None:
            try:
                self._steer(tool_call, params, result, session, eff)
            except Exception:
                logger.exception("coworker: advisor steering failed for {}", self._key)
        if tool_call.name == "advisor":
            return
        if (
            eff is None
            or eff.mode != advisor_state.MODE_CODING
            or eff.uses >= eff.max_uses
            or not load_coworker_config().advisor.stuck_detection
        ):
            return
        args: dict[str, Any] = {}
        if isinstance(params, dict):
            args = cast("dict[str, Any]", params)
        elif isinstance(tool_call.arguments, dict):
            args = cast("dict[str, Any]", tool_call.arguments)
        sig = failure_signature(tool_call.name, args, result)
        if self._stuck.record(sig):
            advisor_state.add_stuck_id(session, tool_call.id)

    async def before_execute_tool(
        self,
        context: AgentHookContext,
        tool_call: ToolCallRequest,
        tool: Any,
        params: Any,
    ) -> str | None:
        """Phase 8: direct writes outside the drafts folder go through a reviewed proposal instead."""
        staged = self._staging_block(tool_call, params)
        if staged is not None:
            return staged
        # C2: block a first commit/push/reset/rm that follows unreviewed writes (once per write count).
        if not self._key or self._reviewed_since_write or self._gated_at_write == self._written:
            return None
        if not policy.is_irreversible_call(tool_call.name, params if params is not None else tool_call.arguments):
            return None
        try:
            return await self._commit_gate(tool_call)
        except Exception:
            logger.exception("coworker: commit gate failed for {}", self._key)
            return None

    def _staging_block(self, tool_call: ToolCallRequest, params: Any) -> str | None:
        if tool_call.name not in WRITE_TOOLS or not self._key:
            return None
        if not load_coworker_config().staging.enabled:
            return None
        session = get_session(self._key)
        root = project_root_for(session) if session is not None else None
        if session is None or root is None:
            return None
        typed = as_dict(params) or as_dict(tool_call.arguments) or {}
        paths = params_paths(tool_call.name, typed)
        open_tabs = {str(p) for p in as_list(session_state(session).get("open_tabs")) or []}
        if tool_call.name == "file_write_staged":
            return None  # the proposal itself is the reviewed path
        # apply_patch without readable paths cannot be checked, so it is refused rather than guessed at.
        blocked = blocked_paths(paths, root, open_tabs) if paths else ["(paths not readable in this call)"]
        if not blocked:
            return None
        logger.info("coworker: staged-write guard blocked {} for {}: {}", tool_call.name, self._key, blocked)
        return json.dumps({"status": "staging_required", "message": block_message(blocked)}, ensure_ascii=False)

    async def _commit_gate(self, tool_call: ToolCallRequest) -> str | None:
        session = get_session(self._key)
        if session is None or not self._steering_eligible():
            return None
        eff = advisor_state.effective(session)
        if eff is None or eff.mode != advisor_state.MODE_CODING or not self._advisor_usable(eff):
            return None
        cfg = load_coworker_config().advisor
        if not policy.resolve_policy(cfg, self._executor_model()).commit_gate:
            return None
        self._gated_at_write = self._written
        root = project_root_for(session)
        summary = await asyncio.to_thread(git_summary, root, max_chars=1500) if root is not None else ""
        logger.info("coworker: commit gate blocked {} for {}", tool_call.name, self._key)
        payload = {
            "status": "advisor_review_required",
            "reason": (
                f"You wrote {self._written} time(s) this run and have not had a successful advisor review "
                f"since the last write. `{tool_call.name}` is hard to undo, so it was NOT executed."
            ),
            "next": (
                "Call advisor(focus=<what you changed and what you are unsure about>) now — the harness "
                "attaches the real diff. Then repeat this call; it will go through this time."
            ),
            "git": summary,
        }
        return json.dumps(payload, ensure_ascii=False)

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
                kw_status = keepalive.status_for(session)
                expires_at = kw_status.get("expires_at")
                metrics_store.record_turn(
                    session_key=self._key,
                    provider=provider_name,
                    model=model,
                    usage=context.usage,
                    optimize=optimizer.describe(self._key),
                    warm=bool(expires_at is not None and float(expires_at) > time.time()),
                    source=current_llm_usage_source(),
                )

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
        svc = services()
        if svc is None:
            return messages, tools
        cfg = load_coworker_config()
        session = get_session(self._key)
        if session is None:
            return messages, tools

        from nanobot.coworker.agents.prompt import resolve_home

        persona_agent = resolve_persona(session, cfg)
        home = resolve_home(persona_agent, svc.workspace) if persona_agent else None
        is_direct = persona_agent is not None and home is not None

        if is_direct and persona_agent is not None and messages and messages[0].get("role") == "system":
            old_content = messages[0].get("content")
            archived_summary = ""
            archived_marker = "[Archived Context Summary]"
            if isinstance(old_content, str) and archived_marker in old_content:
                idx = old_content.rfind(archived_marker)
                archived_summary = old_content[idx:].strip()

            from nanobot.coworker.agents.prompt import build_system_prompt
            from nanobot.security.workspace_access import workspace_scope_from_metadata

            scope = workspace_scope_from_metadata(
                getattr(session, "metadata", None),
                default_workspace=svc.workspace,
                default_restrict_to_workspace=bool(
                    svc.tools_config and svc.tools_config.restrict_to_workspace
                ),
            )
            new_prompt = build_system_prompt(
                persona_agent,
                project_root=scope.project_path,
                svc=svc,
                roster=cfg.room.agents,
                role="direct",
                channel=self._turn.channel,
            )
            if archived_summary:
                new_prompt = f"{new_prompt}\n\n---\n\n{archived_summary}"
            messages = [{**messages[0], "content": new_prompt}, *messages[1:]]

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
        sections: list[str] = []
        if not is_direct and persona_agent is not None:
            sections.append(directives.persona_section(persona_agent))
        if advisor_eff is not None:
            brainstorm = advisor_eff.mode == advisor_state.MODE_BRAINSTORM
            sections.append(directives.ADVISOR_BRAINSTORM if brainstorm else directives.ADVISOR)
            if not brainstorm and cfg.advisor.ledger:
                open_ledger = advisor_state.ledger(session)
                if advisor_ledger.has_content(open_ledger):
                    sections.append(
                        directives.advisor_commitments(
                            advisor_ledger.render(open_ledger, ids=False, unmet_done_only=True)
                        )
                    )
        if room_on:
            roster_agents = (
                [a for a in cfg.room.agents if a.id.lower() != persona_agent.id.lower()]
                if persona_agent is not None
                else cfg.room.agents
            )
            sections += [directives.room_owner(roster_agents), directives.ROOM_STATE]
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
            messages = _annotate_notes(messages, advisor_state.result_notes(session))

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
        if not cfg.staging.enabled:
            hidden.add(STAGED_TOOL)

        if persona_agent is not None:
            if persona_agent.memory != "thread+notes":
                hidden.add("agent_notes")
            if tools:
                from nanobot.coworker.agents.toolset import matches_any

                always_keep = {
                    "room_state",
                    "room_delegate",
                    "agents_list",
                    "agent_notes",
                    ADVISOR_TOOL,
                    WASTED_TOOL,
                    CODING_TOOL,
                    *WORKFLOW_TOOLS,
                }
                for t in tools:
                    tname = _tool_name(t)
                    if tname in always_keep:
                        continue
                    if persona_agent.tools.allow and not matches_any(tname, persona_agent.tools.allow):
                        hidden.add(tname)
                    if persona_agent.tools.deny and matches_any(tname, persona_agent.tools.deny):
                        hidden.add(tname)
        else:
            hidden.add("agent_notes")

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
        if not self._key:
            return None
        cfg = load_coworker_config()
        result_turn = self._kind == KIND_CODING_RESULT
        room_review_turn = self._kind == scheduler.KIND_ROOM_REVIEW
        if self._kind is not None and not (result_turn or room_review_turn):
            return None
        if not (result_turn or room_review_turn) and self._genuine_text is None:
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
        if eff is None:
            return None
        scan = policy.scan_run(context.messages if context is not None else [])
        # B2 done-gate: the advisor still has open items and this run did real work.
        if (
            cfg.advisor.ledger
            and not self._gated
            and eff.mode != advisor_state.MODE_BRAINSTORM
            and scan.work_total > 0
        ):
            open_ledger = advisor_state.ledger(session)
            gate_dod = cfg.advisor.output_template and cfg.advisor.done_gate_done_when
            if open_ledger is not None and policy.done_gate_applies(
                open_ledger, include_done_when=gate_dod
            ):
                self._gated = True
                advisor_state.record_review_nudge(session, kind="done_gate", now=time.time())
                logger.info(
                    "coworker: advisor done-gate for {} ({} open items)",
                    self._key, advisor_ledger.open_count(open_ledger, include_done_when=gate_dod),
                )
                return policy.done_gate_text(open_ledger)
        if room_review_turn:
            return self._room_review_nudge(cfg, eff, session)
        if self._nudged or not cfg.advisor.review_nudge or eff.uses >= eff.max_uses:
            return None
        try:
            model_key = runtime_for_preset(eff.preset).model
        except Exception:
            return None
        if breaker_open_seconds(model_key) > 0:
            logger.warning("coworker: advisor review nudge skipped, circuit open for {}", model_key)
            return None
        pol = policy.resolve_policy(cfg.advisor, self._executor_model())
        decision: policy.NudgeDecision | None = None
        if eff.mode != advisor_state.MODE_BRAINSTORM:
            decision = policy.decide_review_nudge(
                scan,
                first_gap=pol.first_gap,
                reconsult_gap=pol.reconsult_gap,
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
                first_gap=pol.first_gap,
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


    def _room_review_nudge(self, cfg: CoworkerConfig, eff: advisor_state.AdvisorEffective, session: Any) -> str | None:
        """Review turn after teammates finished: ask for one advisor consult before the final report.

        Coding-mode only (brainstorm keeps its own gate). Once per turn, and never after a successful
        consult in this same turn. Skipped when the advisor budget is spent or its circuit is open.
        """
        if eff.mode != advisor_state.MODE_CODING or self._nudged or self._consulted_this_turn:
            return None
        if not (cfg.advisor.review_nudge and cfg.advisor.room_review_nudge) or eff.uses >= eff.max_uses:
            return None
        try:
            model_key = runtime_for_preset(eff.preset).model
        except Exception:
            return None
        if breaker_open_seconds(model_key) > 0:
            logger.warning("coworker: room review nudge skipped, circuit open for {}", model_key)
            return None
        self._nudged = True
        advisor_state.record_review_nudge(session, kind="room_review", now=time.time())
        logger.info("coworker: room review advisor nudge for {}", self._key)
        return policy.review_nudge_text(policy.NudgeDecision("room_review", 0))


def create_coworker_hook(turn: AgentTurnHookContext) -> AgentHook | None:
    if turn.ephemeral or not turn.session_key:
        return None
    return CoworkerHook(turn)
