"""Advisor output template: ledger fields (goal, done_when, steps, unverified), merge, render, prompt, gate."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.hook import AgentHookContext, AgentTurnHookContext
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.coworker import runtime
from nanobot.coworker.advisor import ledger as advisor_ledger
from nanobot.coworker.advisor import policy
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.advisor.consult import (
    ADVISOR_BREVITY,
    LEDGER_INSTRUCTION,
    LEDGER_INSTRUCTION_V2,
    OUTPUT_TEMPLATE,
    TEMPLATE_BREVITY,
    run_consult,
)
from nanobot.coworker.advisor.tool import AdvisorTool
from nanobot.coworker.config import AdvisorConfig, CoworkerConfig
from nanobot.coworker.hook import CoworkerHook
from nanobot.providers.base import LLMResponse

KEY = "cli:direct"

MESSAGES = [
    {"role": "system", "content": "EXECUTOR SYSTEM"},
    {"role": "user", "content": "fix the bug"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "a.py"}'}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "def f(): ..."},
]


def _reply(block: dict[str, Any], prose: str = "Guidance.") -> str:
    return f"{prose}\n\n```json\n{json.dumps(block)}\n```\n"


def _parse(block: dict[str, Any]) -> dict[str, Any]:
    _, ledger = advisor_ledger.parse_ledger(_reply(block))
    assert ledger is not None
    return ledger


# ---------- parsing ----------

def test_parse_normalizes_template_fields_and_enforces_limits() -> None:
    ledger = _parse({
        "verdict": "revise",
        "goal": "  Make  the   parser reject empty input  ",
        "done_when": [
            "plain string condition",
            {"text": "pytest tests/test_parser.py passes", "check": "uv run pytest tests/test_parser.py", "status": "MET"},
            {"text": "pending one", "check": "null", "status": "bogus"},
            {"text": "plain string condition"},  # duplicate
            {"text": ""},  # empty
            *({"text": f"extra {i}"} for i in range(10)),
        ],
        "steps": [f"step {i}" for i in range(12)] + ["", "  "],
        "unverified": ["tests pass"],
    })
    assert ledger["goal"] == "Make the parser reject empty input"
    done = ledger["done_when"]
    assert len(done) == advisor_ledger.DONE_MAX_ITEMS
    assert done[0] == {"text": "plain string condition", "check": None, "status": None}
    assert done[1] == {"text": "pytest tests/test_parser.py passes", "check": "uv run pytest tests/test_parser.py", "status": "met"}
    assert done[2] == {"text": "pending one", "check": None, "status": None}  # "null" check and unknown status dropped
    assert len(ledger["steps"]) == advisor_ledger.STEP_MAX_ITEMS and ledger["steps"][0] == "step 0"
    assert ledger["unverified"] == ["tests pass"]


def test_parse_leaves_template_keys_out_when_missing_or_empty() -> None:
    ledger = _parse({"verdict": "proceed", "goal": "null", "done_when": [], "steps": [], "unverified": []})
    for key in advisor_ledger.TEMPLATE_KEYS:
        assert key not in ledger
    assert advisor_ledger.parse_ledger(_reply({"goal": "only a goal"}))[1] == {
        "verdict": "proceed", "next_checkpoint": None,
        "must_fix": [], "verify": [], "do_not": [], "pitfalls": [], "goal": "only a goal",
    }


def test_shape_reports_what_the_reply_contained() -> None:
    assert advisor_ledger.shape(None) == {"parsed": 0, "goal": 0, "done_when": 0, "steps": 0, "unverified": 0}
    full = _parse({"goal": "g", "done_when": ["a", "b"], "steps": ["s"], "unverified": ["u"]})
    assert advisor_ledger.shape(full) == {"parsed": 1, "goal": 1, "done_when": 2, "steps": 1, "unverified": 1}


# ---------- merge ----------

def test_merge_keeps_goal_and_definition_of_done_when_the_reply_is_silent() -> None:
    first = _parse({"goal": "ship it", "done_when": [{"text": "A", "status": "met"}, {"text": "B", "status": "open"}],
                    "steps": ["s1"], "must_fix": ["m1"], "unverified": ["u1"]})
    second = _parse({"verdict": "proceed", "must_fix": []})
    merged = advisor_ledger.merge(advisor_ledger.merge(None, first), second)
    assert merged["goal"] == "ship it"
    assert [(d["text"], d["status"]) for d in merged["done_when"]] == [("A", "met"), ("B", "open")]
    assert merged["must_fix"] == []  # open issues are still closed by silence
    assert "steps" not in merged and "unverified" not in merged  # a stale plan is not carried over


def test_merge_treats_an_empty_done_when_as_silence_not_as_deletion() -> None:
    first = advisor_ledger.merge(None, _parse({"done_when": ["A"]}))
    second = _parse({"verdict": "revise", "done_when": []})
    assert [d["text"] for d in advisor_ledger.merge(first, second)["done_when"]] == ["A"]


def test_merge_replaces_the_list_and_inherits_status_of_unchanged_items() -> None:
    first = advisor_ledger.merge(None, _parse({"done_when": [{"text": "A", "status": "met"}, {"text": "B", "status": "open"}]}))
    second = _parse({"done_when": [{"text": "a"}, {"text": "B", "status": "met"}, {"text": "C"}]})
    merged = advisor_ledger.merge(first, second)["done_when"]
    assert [(d["text"], d["status"]) for d in merged] == [("a", "met"), ("B", "met"), ("C", "open")]


# ---------- render / counts ----------

def test_ledger_without_template_keys_renders_exactly_as_before() -> None:
    ledger = _parse({"verdict": "revise", "must_fix": ["a"], "verify": ["v"], "do_not": ["x"], "pitfalls": ["p"],
                     "next_checkpoint": "after_steps:6"})
    assert advisor_ledger.render(ledger, ids=False) == (
        "Verdict: revise\nMust fix:\n- a\nVerify:\n- v\nDo not:\n- x\nPitfalls:\n- p\nNext checkpoint: after_steps:6"
    )


def test_render_shows_goal_definition_of_done_and_steps_in_order() -> None:
    ledger = advisor_ledger.merge(None, _parse({
        "goal": "G", "must_fix": ["m"],
        "done_when": [{"text": "done one", "check": "pytest", "status": "met"}, {"text": "open one", "status": "unknown"},
                      {"text": "todo"}],
        "steps": ["first", "second"], "do_not": ["d"], "unverified": ["u"],
    }))
    text = advisor_ledger.render(ledger, ids=False, steps=True)
    lines = text.splitlines()
    assert lines[:2] == ["Verdict: proceed", "Goal: G"]
    assert lines.index("Must fix:") < lines.index("Definition of done:") < lines.index("Steps:") < lines.index("Do not:")
    assert "- [x] done one (check: pytest)" in lines and "- [?] open one" in lines and "- [ ] todo" in lines
    assert "1. first" in lines and "2. second" in lines and lines[-2:] == ["Unverified:", "- u"]
    # Steps are never pinned; finished items drop out of the pinned view.
    pinned = advisor_ledger.render(ledger, ids=False, unmet_done_only=True)
    assert "Steps:" not in pinned and "done one" not in pinned and "- [?] open one" in pinned


def test_unmet_items_count_only_when_asked_and_unknown_is_unmet() -> None:
    ledger = advisor_ledger.merge(None, _parse({
        "must_fix": ["m"], "done_when": [{"text": "a", "status": "met"}, {"text": "b", "status": "unknown"}, {"text": "c"}],
    }))
    assert advisor_ledger.open_count(ledger) == 1
    assert advisor_ledger.open_count(ledger, include_done_when=True) == 3
    assert advisor_ledger.has_content(advisor_ledger.merge(None, _parse({"goal": "only a goal"})))


# ---------- done-gate ----------

def test_done_gate_counts_definition_of_done_only_when_enabled() -> None:
    ledger = advisor_ledger.merge(None, _parse({"done_when": [{"text": "ship", "status": "open"}]}))
    assert not policy.done_gate_applies(ledger)
    assert policy.done_gate_applies(ledger, include_done_when=True)
    text = policy.done_gate_text(ledger)
    assert "Definition-of-done item not yet met" in text and "Definition of done:" in text
    plain = policy.done_gate_text(advisor_ledger.merge(None, _parse({"must_fix": ["m"]})))
    assert "Definition-of-done" not in plain


def _hook(env, **advisor: Any) -> tuple[CoworkerHook, Any]:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", **advisor)))
    session = env.sessions.get_or_create(KEY)
    hook = CoworkerHook(AgentTurnHookContext(channel="cli", chat_id="direct", session_key=KEY))
    hook._genuine_text = "build it"
    return hook, session


def _work_run() -> list[dict[str, Any]]:
    call = {"id": "1", "type": "function", "function": {"name": "write_file", "arguments": '{"path": "a.py"}'}}
    return [{"role": "user", "content": "go"}, {"role": "assistant", "content": "", "tool_calls": [call]}]


def test_hook_gate_needs_both_flags_before_unmet_definition_of_done_blocks_finish(env, monkeypatch) -> None:
    monkeypatch.setattr("nanobot.coworker.hook.runtime_for_preset", lambda p: SimpleNamespace(model="strong"))
    for flags, expect_gate in (
        ({"output_template": True, "done_gate_done_when": True}, True),
        ({"output_template": True, "done_gate_done_when": False}, False),
        ({"output_template": False, "done_gate_done_when": True}, False),
    ):
        hook, session = _hook(env, review_nudge=False, **flags)
        advisor_state.apply_ledger(session, advisor_ledger.merge(None, _parse({"done_when": [{"text": "ship"}]})))
        hook._iter_ctx = AgentHookContext(iteration=1, messages=_work_run())
        text = hook.continuation()
        assert (text is not None) is expect_gate, flags
        advisor_state._slot(session).pop("ledger", None)


def test_pinned_commitments_carry_goal_and_unmet_items_but_not_steps(env) -> None:
    hook, session = _hook(env, output_template=True)
    advisor_state.apply_ledger(session, advisor_ledger.merge(None, _parse({
        "goal": "Make X work", "done_when": [{"text": "A done", "status": "met"}, {"text": "B open"}], "steps": ["do the thing"],
    })))
    messages = [{"role": "system", "content": "BASE"}, {"role": "user", "content": "hi"}]
    out, _ = hook.transform_request(AgentHookContext(iteration=0, messages=messages), messages, None, stateful=False)
    system = out[0]["content"]
    assert "## Advisor commitments (open)" in system and "Goal: Make X work" in system
    assert "- [ ] B open" in system and "A done" not in system and "do the thing" not in system


# ---------- consult prompt ----------

def _runtime(content: str = "advice") -> SimpleNamespace:
    provider = SimpleNamespace(chat_with_retry=AsyncMock(return_value=LLMResponse(content=content, finish_reason="stop")))
    return SimpleNamespace(provider=provider, model="strong-model")


@pytest.mark.asyncio
async def test_template_changes_the_prompt_only_when_asked() -> None:
    rt = _runtime()
    await run_consult(messages=MESSAGES, runtime=rt, focus="f", max_tokens=64, timeout_s=5, allow_thin=True,
                      ledger=True, template=True)
    system, prompt = (m["content"] for m in rt.provider.chat_with_retry.await_args.kwargs["messages"])
    assert OUTPUT_TEMPLATE in system and system.endswith(LEDGER_INSTRUCTION_V2)
    assert TEMPLATE_BREVITY in prompt and ADVISOR_BREVITY not in prompt

    rt = _runtime()
    await run_consult(messages=MESSAGES, runtime=rt, focus="f", max_tokens=64, timeout_s=5, allow_thin=True, ledger=True)
    system, prompt = (m["content"] for m in rt.provider.chat_with_retry.await_args.kwargs["messages"])
    assert OUTPUT_TEMPLATE not in system and system.endswith(LEDGER_INSTRUCTION)
    assert ADVISOR_BREVITY in prompt and TEMPLATE_BREVITY not in prompt


@pytest.mark.asyncio
async def test_brainstorm_never_gets_the_template() -> None:
    rt = _runtime()
    await run_consult(messages=MESSAGES, runtime=rt, focus="f", max_tokens=64, timeout_s=5, allow_thin=True,
                      brainstorm=True, ledger=True, template=True)
    system = rt.provider.chat_with_retry.await_args.kwargs["messages"][0]["content"]
    assert OUTPUT_TEMPLATE not in system and LEDGER_INSTRUCTION_V2 not in system


# ---------- tool end to end ----------

@pytest.mark.asyncio
async def test_tool_keeps_the_definition_of_done_across_consults_and_records_shape(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(
        preset="strong", output_template=True, evidence_pack=False, refill_steps=0, max_uses=5)))
    first = _reply({"verdict": "revise", "goal": "Fix the parser", "must_fix": ["empty input crashes"],
                    "done_when": [{"text": "empty input is rejected", "check": "pytest -k empty", "status": "open"}],
                    "steps": ["add a guard in parse()"]}, prose="Verdict: revise.")
    second = _reply({"verdict": "proceed"}, prose="Looks fine now.")  # says nothing about the definition of done
    provider = SimpleNamespace(chat_with_retry=AsyncMock(side_effect=[
        LLMResponse(content=first, finish_reason="stop"), LLMResponse(content=second, finish_reason="stop")]))
    monkeypatch.setattr("nanobot.coworker.advisor.tool.runtime_for_preset",
                        lambda p: SimpleNamespace(provider=provider, model="strong"))
    session = env.sessions.get_or_create(KEY)
    runtime.remember_live_messages(KEY, MESSAGES)
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key=KEY)):
        out1 = await AdvisorTool().execute(focus="check the parser")
        await AdvisorTool().execute(focus="check again")
    assert "```json" not in str(out1) and "Verdict: revise." in str(out1)

    ledger = advisor_state.ledger(session)
    assert ledger is not None and ledger["goal"] == "Fix the parser"
    assert [(d["text"], d["status"]) for d in ledger["done_when"]] == [("empty input is rejected", "open")]
    assert ledger["must_fix"] == [] and "steps" not in ledger

    shapes = [h["shape"] for h in advisor_state.history(session)]
    assert shapes[0] == {"parsed": 1, "goal": 1, "done_when": 1, "steps": 1, "unverified": 0}
    assert shapes[1]["done_when"] == 0  # measured on the reply, not on the merged ledger

    calls = provider.chat_with_retry.await_args_list
    assert OUTPUT_TEMPLATE in calls[0].kwargs["messages"][0]["content"]
    second_prompt = calls[1].kwargs["messages"][1]["content"]
    assert "Definition of done:" in second_prompt and "- [ ] empty input is rejected (check: pytest -k empty)" in second_prompt
    assert "Steps:" in second_prompt and "add a guard in parse()" in second_prompt  # earlier plan shown to the advisor


@pytest.mark.asyncio
async def test_tool_without_the_flag_records_no_shape_and_uses_the_old_prompt(env, monkeypatch) -> None:
    env.configure(CoworkerConfig(advisor=AdvisorConfig(preset="strong", evidence_pack=False)))
    provider = SimpleNamespace(chat_with_retry=AsyncMock(return_value=LLMResponse(
        content=_reply({"verdict": "proceed", "must_fix": ["m"]}), finish_reason="stop")))
    monkeypatch.setattr("nanobot.coworker.advisor.tool.runtime_for_preset",
                        lambda p: SimpleNamespace(provider=provider, model="strong"))
    session = env.sessions.get_or_create(KEY)
    runtime.remember_live_messages(KEY, MESSAGES)
    with request_context(RequestContext(channel="cli", chat_id="direct", session_key=KEY)):
        await AdvisorTool().execute(focus="check")
    system = provider.chat_with_retry.await_args.kwargs["messages"][0]["content"]
    assert system.endswith(LEDGER_INSTRUCTION) and OUTPUT_TEMPLATE not in system
    assert "shape" not in advisor_state.history(session)[-1]
