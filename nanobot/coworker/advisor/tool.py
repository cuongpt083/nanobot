"""``advisor`` tool — consult a stronger model on the current session."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import time
from typing import Any

from nanobot.agent.tools.base import ToolResult, tool_parameters
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import run_consult
from nanobot.coworker.config import load_coworker_config
from nanobot.coworker.runtime import live_messages, runtime_for_preset
from nanobot.coworker.tools_base import CoworkerTool

ADVISOR_TOOL = "advisor"


@tool_parameters({
    "type": "object",
    "properties": {
        "focus": {
            "type": "string",
            "description": "Optional, 1-2 sentences: the specific question or decision you want the advisor to weigh in on.",
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
            "`focus` narrows the question (it supplements the forwarded transcript, never replaces it). "
            "When to call is covered by the Advisor section of your system prompt. Non-advice results: "
            '{status:"insufficient_context"} (orient first, then call again — free), '
            '{status:"max_uses_exceeded"} or {status:"advisor_error"} (continue on your own judgment).'
        )

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, focus: str | None = None, **kwargs: Any) -> ToolResult:
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
        messages = live_messages(request.session_key) or list(session.messages)
        started = time.monotonic()
        result = await run_consult(
            messages=messages,
            runtime=runtime,
            focus=(focus or "")[:500] or None,
            max_tokens=eff.max_tokens,
            timeout_s=load_coworker_config().advisor.timeout_seconds,
            allow_thin=eff.early_refused or eff.uses > 0,
            session_key=request.session_key,
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
        uses = advisor_state.count_use(session)
        return ToolResult(
            f"ADVISOR ({result.model}) — advice {uses}/{eff.max_uses}:\n\n{result.text}\n\n---\n"
            "(Reminder: consult the advisor again when the same error recurs, when a result contradicts your "
            "plan, before switching approach, and ONCE before declaring the task done — after saving your work.)"
        )
