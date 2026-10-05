"""Slash commands for the coworker features."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from nanobot.bus.events import OutboundMessage
from nanobot.coworker.advisor import state as advisor_state
from nanobot.coworker.agents.home import agent_home_path, init_agent
from nanobot.coworker.coding.commands import cmd_code
from nanobot.coworker.config import coworker_config_path, load_coworker_config
from nanobot.coworker.context import keepalive, optimizer
from nanobot.coworker.room import scheduler
from nanobot.coworker.room.store import RoomStateStore, RoomTranscript, room_id_for
from nanobot.coworker.runtime import inject_turn, services
from nanobot.coworker.workflows import drive
from nanobot.coworker.workflows.distill import distill
from nanobot.coworker.workflows.registry import list_workflows

if TYPE_CHECKING:
    from nanobot.command.router import CommandContext, CommandRouter
    from nanobot.session.manager import Session


def _reply(ctx: CommandContext, text: str) -> OutboundMessage:
    return OutboundMessage(
        channel=ctx.msg.channel,
        chat_id=ctx.msg.chat_id,
        content=text,
        metadata={**dict(ctx.msg.metadata or {}), "render_as": "text"},
    )


def _session(ctx: CommandContext) -> Session:
    return ctx.session or ctx.loop.sessions.get_or_create(ctx.key)


def _route(ctx: CommandContext) -> tuple[str, str]:
    if ctx.msg.channel == "system" and ":" in ctx.msg.chat_id:
        channel, chat_id = ctx.msg.chat_id.split(":", 1)
        return channel, chat_id
    return ctx.msg.channel, ctx.msg.chat_id


_ADVISOR_USAGE = "Usage: /advisor on [preset] | off | brainstorm | code | reset | <preset> | default | status"


async def cmd_advisor(ctx: CommandContext) -> OutboundMessage:
    session = _session(ctx)
    head, _, rest = ctx.args.strip().partition(" ")
    verb, rest = head.lower(), rest.strip()
    try:
        if verb in ("", "status"):
            pass
        elif verb == "on":
            advisor_state.apply_switch(session, enabled=True, preset=rest or None)
        elif verb == "off":
            advisor_state.apply_switch(session, enabled=False)
        elif verb == "brainstorm":
            advisor_state.apply_switch(session, enabled=True, mode=advisor_state.MODE_BRAINSTORM, preset=rest or None)
        elif verb == "code":
            advisor_state.apply_switch(session, mode=advisor_state.MODE_CODING)
        elif verb == "reset":
            advisor_state.reset_uses(session)
        elif verb == "default":
            advisor_state.set_preset(session, None)
        else:
            advisor_state.apply_switch(session, enabled=True, preset=head)
    except ValueError as exc:
        return _reply(ctx, f"⚠️ {exc}\n{_ADVISOR_USAGE}")
    if verb not in ("", "status"):
        ctx.loop.sessions.save(session)
    eff = advisor_state.effective(session)
    if eff is None:
        return _reply(ctx, f"🧭 Advisor: off for this session.\n{_ADVISOR_USAGE}")
    return _reply(
        ctx,
        f"🧭 Advisor: on ({eff.mode}), preset `{eff.preset}` — {eff.uses}/{eff.max_uses} consults used.\n"
        f"{_ADVISOR_USAGE}",
    )


async def cmd_room(ctx: CommandContext) -> OutboundMessage:
    session = _session(ctx)
    arg = ctx.args.strip().lower()
    cfg = load_coworker_config()
    if arg in ("on", "off"):
        scheduler.set_armed(session, arg == "on")
        ctx.loop.sessions.save(session)
    elif arg == "reset":
        svc = services()
        if svc is not None:
            rid = room_id_for(ctx.key)
            RoomStateStore(svc.workspace, rid).clear()
            RoomTranscript(svc.workspace, rid).clear()
    if not cfg.room.agents:
        return _reply(ctx, f"👥 No room agents configured — add `room.agents` to {coworker_config_path()}.")
    roster = "\n".join(
        f"- {(a.emoji + ' ') if a.emoji else ''}{a.name or a.id} (`{a.id}`): {a.bio}" for a in cfg.room.agents
    )
    state = "ON" if scheduler.is_armed(session) else "off"
    return _reply(ctx, f"👥 Room: {state}\n{roster}\nUsage: /room on | off | reset")


async def cmd_workflow(ctx: CommandContext) -> OutboundMessage:
    svc = services()
    if svc is None:
        return _reply(ctx, "Workflow engine not bound yet — send a normal message first.")
    session = _session(ctx)
    action, _, rest = ctx.args.strip().partition(" ")
    action = action.lower() or "list"
    if action == "list":
        items = list_workflows(svc.workspace)
        if not items:
            return _reply(ctx, f"No workflows in {svc.workspace / 'workflows'}.")
        return _reply(ctx, "\n".join(f"- `{w.ref}` — {w.name}: {w.description} ({w.steps} steps)" for w in items))
    if action == "status":
        return _reply(ctx, json.dumps(drive.status(session, svc.workspace), ensure_ascii=False, indent=2))
    if action == "cancel":
        result = drive.cancel(session, svc.workspace)
        ctx.loop.sessions.save(session)
        return _reply(ctx, json.dumps(result, ensure_ascii=False))
    if action == "save":
        try:
            result = distill(svc.workspace, rest.strip(), list(session.messages))
        except Exception as exc:
            return _reply(ctx, f"⚠️ {exc}")
        issues = "\n".join(f"- {e}" for e in [*result.validation.errors, *result.validation.warnings])
        return _reply(ctx, f"📝 Draft `{result.ref}` written ({result.steps} steps) at {result.dir}\n{issues}".strip())
    if action in ("run", "resume", "repin"):
        try:
            if action == "run":
                ref, _, run_input = rest.strip().partition(" ")
                drive.start(session, svc.workspace, ref, run_input)
            elif not drive.resume(session, accept_graph_change=action == "repin"):
                return _reply(ctx, "No workflow run bound to this session.")
            injection, note = drive.on_turn_end(
                session, svc.workspace, final_content=None, step_turn=None, genuine_user_text=None
            )
        except Exception as exc:
            return _reply(ctx, f"⚠️ {exc}")
        ctx.loop.sessions.save(session)
        if injection is None:
            return _reply(ctx, note or "Nothing to drive.")
        channel, chat_id = _route(ctx)
        await inject_turn(
            session_key=ctx.key,
            channel=channel,
            chat_id=chat_id,
            content=injection.content,
            kind=drive.KIND_WORKFLOW_STEP,
            extra={"workflow_run": injection.run_id, "workflow_step": injection.step},
        )
        return _reply(ctx, f"▶️ Workflow run {injection.run_id}: starting step `{injection.step}`.")
    return _reply(ctx, "Usage: /workflow list | run <ref> [input] | status | cancel | resume | repin | save <slug>")


async def cmd_ctx(ctx: CommandContext) -> OutboundMessage:
    info = {"optimizer": optimizer.describe(ctx.key), "keepalive": keepalive.status(ctx.key)}
    return _reply(ctx, "🧠 Context cache state:\n" + json.dumps(info, ensure_ascii=False, indent=2))


async def cmd_agent(ctx: CommandContext) -> OutboundMessage:
    svc = services()
    if svc is None:
        return _reply(ctx, "Coworker runtime services not bound yet — send a normal message first.")
    workspace = svc.workspace
    cfg = load_coworker_config()
    head, _, rest = ctx.args.strip().partition(" ")
    action = head.lower() or "list"
    target_id = rest.strip()

    if action == "list":
        if not cfg.room.agents:
            return _reply(ctx, f"👥 No room agents configured — check {coworker_config_path()}.")
        lines: list[str] = ["👥 Configured room agents:"]
        for a in cfg.room.agents:
            h_status = "configured" if a.home else "none"
            if a.home:
                hp = agent_home_path(workspace, a)
                h_status = f"`{a.home}` (exists)" if hp and hp.exists() else f"`{a.home}` (missing)"
            preset_label = a.preset or "inherit"
            skills_count = len(a.skills.inherit)
            tools_label = f"{len(a.tools.allow)} allow patterns" if a.tools.allow else "all default"
            lines.append(
                f"- **{a.id}** ({a.name or a.id}): home={h_status}, preset=`{preset_label}`, skills={skills_count}, tools={tools_label}"
            )
        return _reply(ctx, "\n".join(lines) + "\n\nUsage: /agent list | init <id> | show <id>")

    if action == "init":
        if not target_id:
            return _reply(ctx, "Usage: /agent init <id>")
        try:
            res = init_agent(workspace, target_id)
            c_str = ", ".join(res["created_files"]) if res["created_files"] else "none"
            s_str = ", ".join(res["skipped_files"]) if res["skipped_files"] else "none"
            return _reply(
                ctx,
                f"🏠 Agent `{target_id}` home initialized at `{res['home']}`.\n- Created: {c_str}\n- Skipped: {s_str}",
            )
        except Exception as exc:
            return _reply(ctx, f"⚠️ Failed to init agent `{target_id}`: {exc}")

    if action == "show":
        if not target_id:
            return _reply(ctx, "Usage: /agent show <id>")
        agent = next((a for a in cfg.room.agents if a.id == target_id), None)
        if agent is None:
            return _reply(ctx, f"⚠️ Agent `{target_id}` not found.")
        details = [
            f"👤 **Agent:** `{agent.id}`",
            f"- **Name:** {agent.name or agent.id}",
            f"- **Emoji:** {agent.emoji}",
            f"- **Bio:** {agent.bio}",
            f"- **Preset:** {agent.preset or 'inherit'}",
            f"- **Backend:** {agent.backend or 'none'}",
            f"- **Home:** {agent.home or 'none'}",
            f"- **Memory:** {agent.memory} (thread turns: {agent.thread_turns})",
            f"- **Max Iterations:** {agent.max_iterations}",
            f"- **Tools Policy:** allow={agent.tools.allow}, deny={agent.tools.deny}",
            f"- **Skills Policy:** inherit={agent.skills.inherit}, deny={agent.skills.deny}",
            f"- **Instructions:**\n{agent.instructions or '(none)'}",
        ]
        return _reply(ctx, "\n".join(details))

    return _reply(ctx, "Usage: /agent list | init <id> | show <id>")


def register(router: CommandRouter) -> None:
    for name, handler in (
        ("/advisor", cmd_advisor),
        ("/room", cmd_room),
        ("/agent", cmd_agent),
        ("/workflow", cmd_workflow),
        ("/ctx", cmd_ctx),
        ("/code", cmd_code),
    ):
        router.exact(name, handler)
        router.prefix(f"{name} ", handler)
