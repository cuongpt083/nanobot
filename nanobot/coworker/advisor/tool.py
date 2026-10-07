"""``advisor`` tool — consult a stronger model on the current session."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker import metrics_store
from nanobot.coworker.advisor import ledger as advisor_ledger
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import current_run, run_consult
from nanobot.coworker.advisor.evidence import collect_evidence, read_requested_files
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.runtime import live_messages, runtime_for_preset, services
from nanobot.coworker.tools_base import CoworkerTool

ADVISOR_TOOL = "advisor"
_ELIDED_ADVICE_RE = re.compile(r"\belided\b|can'?t see|cannot see|not visible|was cut", re.IGNORECASE)


def project_root_for(session: Any) -> Path | None:
    """The project directory the executor works in (the session's workspace scope)."""
    svc = services()
    if svc is None:
        return None
    from nanobot.security.workspace_access import workspace_scope_from_metadata

    try:
        scope = workspace_scope_from_metadata(
            getattr(session, "metadata", None),
            default_workspace=svc.workspace,
            default_restrict_to_workspace=bool(
                svc.tools_config and svc.tools_config.restrict_to_workspace
            ),
        )
    except Exception:
        return Path(svc.workspace)
    return scope.project_path


@tool_parameters({
    "type": "object",
    "properties": {
        "focus": {
            "type": "string",
            "description": (
                "Optional, 1-3 sentences, facts not a verdict to confirm: goal, your current plan, what "
                "you changed, what you are unsure about."
            ),
        },
        "files": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
            "description": (
                "Optional project file paths (max 5) the advisor must read in full, e.g. the plan or spec "
                "you just wrote. The harness attaches their CURRENT content from disk."
            ),
        },
    },
})
class AdvisorTool(CoworkerTool):
    @property
    def name(self) -> str:
        return ADVISOR_TOOL

    @property
    def description(self) -> str:
        return (
            "Consult a stronger advisor model for strategic guidance on your current task. Your ENTIRE "
            "session is forwarded automatically — system prompt, every turn, every tool call and result. "
            "The advisor returns focused advice as text; it has no tools and takes no actions. Optional "
            "`focus` narrows the question (it supplements the forwarded transcript, never replaces it); `files` "
            "attaches the current on-disk content of files you want reviewed. The harness also attaches "
            "git status/diff and recent test output it collected itself. "
            "When to call is covered by the Advisor section of your system prompt. Non-advice results: "
            '{status:"insufficient_context"} (orient first, then call again — free), '
            '{status:"max_uses_exceeded"} or {status:"advisor_error"} (continue on your own judgment).'
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(
        self, focus: str | None = None, files: list[str] | None = None, **kwargs: Any
    ) -> ToolResult:
        request = self.request()
        session = self.session()
        if request is None or session is None:
            return self.payload("advisor_error", error="no active session")
        eff = advisor_state.effective(session)
        if eff is None:
            return self.payload(
                "advisor_disabled",
                fallback="No advisor model is configured for this session. Continue on your own judgment.",
            )
        if eff.uses >= eff.max_uses:
            return self.payload(
                "max_uses_exceeded",
                uses=eff.uses,
                maxUses=eff.max_uses,
                fallback="Advisor budget for this session is spent. Continue without further advice.",
            )
        try:
            runtime = runtime_for_preset(eff.preset)
        except Exception as exc:
            return self.payload(
                "advisor_error",
                error=f"advisor preset {eff.preset!r} cannot be loaded: {exc}",
                fallback="Continue on your own judgment and tell the user the advisor preset is misconfigured.",
            )
        brainstorm = eff.mode == advisor_state.MODE_BRAINSTORM
        messages = live_messages(request.session_key) or list(session.messages)
        cfg = load_coworker_config().advisor
        root = project_root_for(session)
        requested = [f for f in (files or []) if f.strip()][:5]
        evidence = ""
        if cfg.evidence_pack and root is not None:
            if brainstorm:
                evidence = read_requested_files(root, requested) if requested else ""
            else:
                evidence = await collect_evidence(
                    messages, root, requested_files=requested, run_messages=current_run(messages)
                )
        use_ledger = cfg.ledger and not brainstorm
        previous_ledger = advisor_state.ledger(session) if use_ledger else None
        started = time.monotonic()
        result = await run_consult(
            messages=messages,
            runtime=runtime,
            focus=(focus or "")[:500] or None,
            max_tokens=eff.max_tokens,
            timeout_s=load_coworker_config().advisor.timeout_seconds,
            # Brainstorming has no "orient first" phase: the conversation itself is the context.
            allow_thin=(
                brainstorm or eff.early_refused or eff.uses > 0 or advisor_state.user_requested(session)
            ),
            session_key=request.session_key,
            brainstorm=brainstorm,
            evidence=evidence or None,
            ledger=use_ledger,
            ledger_text=advisor_ledger.render(previous_ledger) or None,
        )
        if result.code not in ("insufficient_context", "advisor_unavailable") and result.error != (
            "session transcript is empty"
        ):
            advisor_state.record_consult(
                session,
                model=result.model or eff.preset,
                focus=focus,
                duration_ms=int((time.monotonic() - started) * 1000),
                ok=result.ok,
                now=time.time(),
            )
        if result.code == "insufficient_context":
            advisor_state.mark_early_refusal(session)
            return self.payload(
                "insufficient_context",
                fallback=(
                    "The advisor only sees what YOU have seen — your transcript has no gathered evidence yet, "
                    "so a consult now would return generic advice. Orient FIRST: locate and read the key "
                    "files / fetch the source / reproduce the error. Then call advisor again (this refusal "
                    "did not cost a consult). If the task truly needs no orientation, calling again is accepted."
                ),
            )
        if not result.ok:
            return self.payload(
                "advisor_error",
                error=result.error or "unknown failure",
                fallback=(
                    "The advisor call failed. Continue on your own judgment; you may retry ONCE later. If the "
                    "advisor model itself is unavailable, tell the user so they can pick another preset "
                    "(/advisor <preset>)."
                ),
            )
        from nanobot.coworker.advisor import policy

        scan = policy.scan_run(messages)
        text = result.text
        parsed: dict[str, Any] | None = None
        if use_ledger:
            text, parsed = advisor_ledger.parse_ledger(text)
            if parsed is not None:
                parsed["at"] = time.time()
                parsed = advisor_state.apply_ledger(session, parsed)
        uses = advisor_state.count_use(session)
        advisor_state.clear_user_request(session)
        advisor_state.record_exchange(
            session,
            model=result.model or eff.preset,
            focus=focus,
            advice=text,
            mode=eff.mode,
            now=time.time(),
        )
        metrics_store.record_advisor_consult(
            model=result.model or eff.preset,
            verdict=str((parsed or {}).get("verdict") or ""),
            must_fix=len((parsed or {}).get("must_fix") or []),
            open_items=advisor_ledger.open_count(parsed),
            work_steps_since_last=scan.gap,
            evidence_pack=result.evidence,
            prompt_chars=result.prompt_chars,
            elided_advice=bool(_ELIDED_ADVICE_RE.search(text)),
            checkpoint_set=bool((parsed or {}).get("next_checkpoint")),
            after_write=scan.written_total > 0,
        )
        notes: list[str] = []
        if parsed is not None and parsed.get("next_checkpoint"):
            notes.append(f"Advisor checkpoint: {parsed['next_checkpoint']}")
        remaining = eff.max_uses - uses
        if 0 <= remaining <= advisor_state.LOW_BUDGET_WARNING:
            notes.append(f"Advisor budget: {remaining} consult(s) left; keep them for the final review.")
        tail = ("\n" + "\n".join(notes)) if notes else ""
        return ToolResult(
            f"ADVISOR ({result.model}) — advice {uses}/{eff.max_uses}:\n\n{text}\n\n---\n"
            "(Reminder: consult the advisor again when the same error recurs, when a result contradicts your "
            "plan, before switching approach, and ONCE before declaring the task done — after saving your work.)"
            + tail
        )
