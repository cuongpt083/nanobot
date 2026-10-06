"""System-prompt sections appended only when their feature is active for the session.

Text is deterministic per session state so the cached prompt prefix stays
byte-stable. The advisor timing rules are an A/B-measured prompt ported
near-verbatim from AICoworker (which took them from Claude Code's
ADVISOR_TOOL_INSTRUCTIONS and Anthropic's advisor-tool docs) — reword only with a
reason.
"""

from __future__ import annotations

from nanobot.coworker.config import RoomAgentConfig


def _guest_contract_block() -> str:
    from nanobot.coworker.agents.contract import contract_example

    example = contract_example()
    return "\n".join([
        "End your reply with EXACTLY ONE fenced ```json block matching this schema: "
        '{"summary": string ≤1200 chars, "confidence": "high"|"medium"|"low", '
        '"artifacts": string[], "open_questions": string[]}. summary and confidence are required.',
        "COPY THIS FORMAT (replace values with the real ones):",
        "```json",
        example,
        "```",
    ])

ADVISOR = "\n".join([
    "## Advisor",
    "",
    "You have access to an `advisor` tool backed by a stronger reviewer model. When you call it, your "
    "entire session is automatically forwarded — the task, every tool call you have made, every result "
    "you have seen. The optional `focus` parameter only narrows the question; it never replaces the "
    "forwarded transcript.",
    "",
    "CRITICAL — the advisor only sees what YOU have seen. On a fresh task its advice is only as good as "
    "the evidence in your transcript. Therefore the mandatory order on any non-trivial task is:",
    "",
    "1. ORIENT — locate and read the key files, fetch the source, reproduce the error. Read-only "
    "reconnaissance (read_file, list_dir, find_files, rg/grep, web_fetch). Do NOT write anything yet.",
    "2. CONSULT — call advisor. Now it can see the actual code/data and give specific, load-bearing "
    "advice.",
    "3. PLAN — write the plan (a short written plan in your reply, or create_goal for long multi-turn "
    "work) so the advice funnels into it.",
    "4. EXECUTE.",
    "",
    'Calling advisor before step 1 is a wasted consult — it will be refused with { status: '
    '"insufficient_context" } (costs nothing): gather evidence, then call again. Never treat that '
    "refusal as an error.",
    "",
    "One consult is NOT enough on a multi-step task. You MUST also call advisor:",
    "- When STUCK. Concrete definition — any of: the same error appears twice; two fix attempts have not "
    "made the test/check pass; a tool result contradicts your plan or an assumption you built on. When "
    "one of these happens, calling advisor is the NEXT action, not more solo attempts.",
    "- Before switching to a different approach.",
    "- When you believe the task is complete — BEFORE this final call, make your deliverable durable "
    "(write the file, save the result), then consult for review. Minimum on long tasks: one consult "
    "after orientation, one before declaring done.",
    "- At each MAJOR MILESTONE of a long task — after finishing a module/component and before starting "
    "the next distinct part, and whenever you have written or changed roughly a dozen files/steps since "
    "your last consult. One consult at the start is NOT enough for a multi-file build; a stronger "
    "reviewer catches drift and skipped requirements that compound over a long run. Budget permitting, "
    "err toward re-consulting rather than pressing on solo for dozens of steps.",
    "",
    "Exception: short reactive tasks where the next action is dictated by tool output you just read do "
    "not need repeated consults — the advisor adds most of its value at the two checkpoints above.",
    "",
    "Hard rule: your first write_file / edit_file / apply_patch / state-changing exec call on a "
    "non-trivial task must be preceded by a SUCCESSFUL advisor consult (real advice, not a refusal) in "
    "the same or an earlier turn. Read-only orientation is not state-changing. This is a checkpoint, not "
    "a difficulty judgment.",
    "",
    "Give the advice serious weight. If you follow a step and it fails empirically, or you have "
    "primary-source evidence that contradicts a specific claim (the file says X, the advisor states Y), "
    "adapt. If your evidence points one way and the advisor points another, do not silently switch — "
    'surface the conflict in one more advisor call ("I found X, you suggest Y, which constraint breaks '
    'the tie?") before committing.',
    "",
    'Status handling: { status: "insufficient_context" } → orient, then call again (free). '
    '{ status: "max_uses_exceeded" } or { status: "advisor_error" } → continue with your own judgment; '
    "do not retry in a loop.",
    "",
])

ADVISOR_BRAINSTORM = "\n".join([
    "## Advisor (brainstorm mode)",
    "",
    "The user switched the advisor ON for this conversation. You have an `advisor` tool backed by a "
    "stronger model that acts as a thinking partner: it sees the whole conversation and answers with "
    "reasoning only.",
    "",
    "Use it for discussion, not just for code: call `advisor` BEFORE you give a recommendation, a plan "
    "or a judgment on any open-ended question (strategy, design, trade-offs, writing, decisions). You "
    "do not need to read files or gather evidence first. Put the real question in `focus`. For long replies, "
    "the harness may also ask you to consult the advisor on your draft before finalizing.",
    "",
    "Then answer the user yourself: show where the advisor's view agrees with yours and where it "
    "differs, name the disagreement plainly instead of hiding it, and give your own conclusion. You "
    "may quote the advisor's key point in one short attributed line — never paste the whole advice. "
    "Skip the advisor for greetings, clarifying questions and one-line factual answers.",
])

ROOM_STATE = "\n".join([
    "## Shared room state",
    "`room_state` is a key/value scratchpad shared by EVERY agent in this room. EVERY room turn: START "
    "with `list` (then `get` what is relevant) so you never redo existing work; FINISH by `set`-ing your "
    "own result under your own key. Chat = the human-facing message; room_state = the machine-readable "
    "handoff. Keep keys small and named by purpose (`plan`, `research`, `review:pricing`); store a "
    "summary or a file path, not a whole document.",
])


def agent_capability_highlights(agent: RoomAgentConfig, *, limit: int = 5) -> list[str]:
    """Up to ``limit`` MCP-server / inherited-skill labels from config (not live MCP)."""
    from nanobot.coworker.agents.toolset import mcp_server_from_allow_pattern

    names: set[str] = set()
    for pattern in agent.tools.allow:
        server = mcp_server_from_allow_pattern(pattern)
        if server:
            names.add(server)
    names.update(agent.skills.inherit)
    return sorted(names)[:limit]


def _roster_line(agent: RoomAgentConfig) -> str:
    label = f"- `{agent.id}` — {agent.name or agent.id}"
    if agent.bio:
        label += f": {agent.bio}"
    highlights = agent_capability_highlights(agent)
    if highlights:
        label += f" · {', '.join(highlights)}"
    return label


def room_owner(agents: list[RoomAgentConfig]) -> str:
    roster = (
        "\n".join(_roster_line(a) for a in agents)
        if agents
        else "- _(no other teammates available)_"
    )
    return "\n".join([
        "## Multi-agent room",
        "This conversation is a multi-agent room and you are its COORDINATOR. Teammates:",
        roster,
        "",
        "For any task with more than one distinct area of work, delegate each part whose bio fits a "
        "teammate — a specialist's dedicated turn beats you rushing every part solo. Keep only the parts "
        "no teammate fits, plus planning and final consolidation. Do not ask the user which agent to use.",
        "TO DELEGATE you MUST call `room_delegate({agent, task, context})` once per teammate. `context` is "
        "required: decisions already made, constraints, audience, and what they must not redo. Optional: "
        "`context_keys` (room_state keys), `after` (agent ids already delegated this turn), `deliverable`. "
        "THEN end your turn. Announcing a delegation without calling the tool does nothing. `spawn` is not "
        "a room delegation.",
        "Delegation is asynchronous: never wait or poll inside your turn. The room runs the teammates, "
        "posts their results, and re-summons you with an [auto-room] turn to REVIEW (verify with tools, "
        "open listed artifacts with read_file, do not rubber-stamp) and post ONE final consolidated report "
        "— or delegate a specific fix.",
        "Sequence by dependency: if part B needs part A's output, either delegate A first or pass "
        "`after: [\"A\"]` so B waits. Do not use WAIT_FOR in your own reply.",
    ])


def room_guest(agent: RoomAgentConfig, owner_label: str, teammates: list[RoomAgentConfig]) -> str:
    others = ", ".join(f"`{a.id}`" for a in teammates if a.id != agent.id) or "none"
    lines = [
        f'You are agent "{agent.name or agent.id}" (id `{agent.id}`) in a multi-agent room coordinated by {owner_label}.',
    ]
    if agent.instructions.strip():
        lines += ["", agent.instructions.strip(), ""]
    lines += [
        "You are a FULL agent: EXECUTE the assignment NOW with your tools and reply with concrete results. "
        "This is your only turn until someone delegates to you again — never promise future work.",
        "Only the TEXT of your reply reaches the room: put the entire deliverable in it. "
        "Long deliverables go in `.coworker/rooms/<room>/artifacts/<your-id>/` and are listed in artifacts.",
        "SHARED STATE IS MANDATORY: start with `room_state` `list`; finish by `set`-ing your result under your own key.",
        f"Other teammates: {others}. To hand a sub-task to one, call `room_delegate` with `context` and, "
        "if needed, `after`. If your part genuinely cannot start until another agent's output exists "
        "(and it is not in room_state yet), reply with `WAIT_FOR @<their id>` on its own line plus one sentence.",
        "If no reply is needed, reply exactly REPLY_SKIP.",
    ]
    return "\n".join(lines)


def room_member(agent: RoomAgentConfig, teammates: list[RoomAgentConfig], owner_label: str = "the room coordinator") -> str:
    """Directive for home-backed agents in a multi-agent room.

    Omits persona/instructions since those are provided by the agent's SOUL.md.
    Focuses on room role, room_state scratchpad, delegation rules, and output.
    """
    others = ", ".join(f"`{a.id}`" for a in teammates if a.id != agent.id) or "none"
    lines = [
        "## Multi-agent room member",
        f"You are collaborating in a multi-agent room coordinated by {owner_label}.",
        "You are a FULL agent: EXECUTE the assignment NOW with your tools and reply with concrete results. "
        "This is your only turn until someone delegates to you again — never promise future work.",
        "Only the TEXT of your reply reaches the room. Long deliverables go in "
        "`.coworker/rooms/<room>/artifacts/<your-id>/` and are listed in the JSON `artifacts` array.",
        "SHARED STATE IS MANDATORY: start with `room_state` `list`; finish by `set`-ing your result under your own key.",
        f"Other teammates: {others}. To hand a sub-task to one, call `room_delegate` with `context` and, "
        "if needed, `after`. If your part genuinely cannot start until another agent's output exists "
        "(and it is not in room_state yet), reply with `WAIT_FOR @<their id>` on its own line plus one sentence.",
        "If no reply is needed, reply exactly REPLY_SKIP.",
        _guest_contract_block(),
    ]
    return "\n".join(lines)


WORKFLOWS = "\n".join([
    "## Agent workflows",
    "Registered workflows are deterministic markdown step-graphs. When the user asks to run a "
    "workflow / SOP / quy trình, or a registered workflow clearly matches the requested multi-step task, "
    'call `workflow_run` (action "list" first when unsure of the slug, then "start"). After starting, '
    "finish your reply briefly: the harness drives you through the graph one step per turn. When the user "
    'asks to save what you just did as a workflow ("lưu thành quy trình"), call `workflow_distill`.',
])

WASTED = "\n".join([
    "## Context hygiene",
    "When a tool round-trip turns out to be dead weight (a dead-end search, an obsolete dump you already "
    "extracted what you need from, a step superseded by a later one), call `mark_context_wasted` so it is "
    "dropped from future context. Never flag anything you still need.",
])

CODING = "\n".join([
    "## External coding agent delegation",
    "You can delegate coding work to the Pi coding runtime via `coding_agent`.",
    "",
    "When to do it yourself vs. delegate to Pi:",
    "- DO IT YOURSELF: small edits (1-2 files), config changes, simple tweaks that do not need running full test suites. Use `apply_patch` / file tools.",
    "- DELEGATE TO PI: 3 or more files, new features, multi-file refactoring, or bug fixes requiring test/lint execution loops.",
    "",
    "Structuring the task contract:",
    "- Always provide 'objective' (clear, bounded goal), 'context' (detailed background, architectural decisions, >= 120 chars), and 'acceptance_criteria' (verifiable list).",
    "- Set 'acceptance' if the repository has a test command (e.g. `pytest -q`).",
    "- Use 'mode=\"auto\"' for straightforward tasks or 'mode=\"plan_first\"' when planning is required.",
    "- Use 'wait=True' only for small, quick tasks (< 10 minutes) with no back-and-forth; otherwise run asynchronously.",
    "",
    "Handling coordinator inquiries ('coding_question'):",
    "- If you receive a question from Pi via `ask_coordinator`: answer directly with `coding_agent(action='answer', id=..., question_id=..., answer=...)` if information is known.",
    "- For technical dilemmas or architectural trade-offs, consult `advisor` before answering.",
    "- For business scope or authority questions, ask the user and call `coding_agent(action='answer', id=..., question_id=..., escalated=True)` to extend timeout.",
    "",
    "Handling plan approval ('coding_plan'):",
    "- Verify the plan covers all acceptance criteria. If satisfactory, call `coding_agent(action='approve', id=...)`; if revisions are needed, call `coding_agent(action='revise_plan', id=..., feedback=...)`.",
    "",
    "Post-execution review:",
    "- When you receive `[auto-coding-result]`, read the changes with `coding_agent(action='diff', id=...)` and verify test/review results before advising merge or discard.",
])



# Per-message notes appended to the user turn that addresses an agent by @name. They live on the message
# (not in the system prompt) so the cached prompt prefix stays byte-stable, and are re-derived from the
# text of every such message so earlier turns keep the exact same bytes on later requests.

def coding_mention_note(backend: str, *, enabled: bool) -> str:
    if not enabled:
        return (
            f"[nanobot: the user addressed @{backend}, but coding agents are disabled. Tell them to enable "
            "Settings > Capabilities > Coworker > Coding and add a repository; do not do the work yourself "
            "unless they ask.]"
        )
    return (
        f"[nanobot: the user addressed the coding agent @{backend}. Hand this request to it now: call "
        f"coding_agent(action='start', backend='{backend}', task=<self-contained brief from this message>), "
        "add `acceptance` if the repo has a test command, then end your turn. Do not do the work yourself "
        "and do not ask which agent to use. If the call fails, tell the user exactly what is missing.]"
    )


def advisor_mention_note(*, enabled: bool) -> str:
    if not enabled:
        return (
            "[nanobot: the user addressed @advisor, but the advisor is switched off for this conversation. "
            "Tell them to turn it on with the Advisor switch in the chat header (or /advisor on).]"
        )
    return (
        "[nanobot: the user addressed @advisor. Call the advisor tool now with their question as `focus`, "
        "then answer them, saying where you agree or disagree with it. This consult is user-requested and "
        "will not be refused for thin context.]"
    )


def persona_section(agent: RoomAgentConfig) -> str:
    name = f"{agent.name or agent.id}".strip()
    if agent.emoji:
        name = f"{name} {agent.emoji}".strip()
    parts = [f"## Persona: {name}"]
    if agent.bio:
        parts.append(f"Role: {agent.bio}")
    if agent.instructions and agent.instructions.strip():
        parts.append(agent.instructions.strip())
    return "\n".join(parts)


def persona_direct(agent: RoomAgentConfig) -> str:
    """Directive for a home-backed agent speaking directly with the user."""
    name = f"{agent.name or agent.id}".strip()
    if agent.emoji:
        name = f"{name} {agent.emoji}".strip()
    lines = [
        f"## Persona: {name}",
        "You are speaking directly with the user. Answer in your own voice according to your SOUL.md.",
    ]
    if agent.bio:
        lines.append(f"Role: {agent.bio}")
    if agent.instructions and agent.instructions.strip():
        lines.append(agent.instructions.strip())
    if agent.memory == "thread+notes":
        lines.append(
            "You have access to `agent_notes` to view and record durable lessons learned in your private memory. "
            "Record only reusable lessons, never personal user data."
        )
    return "\n".join(lines)

