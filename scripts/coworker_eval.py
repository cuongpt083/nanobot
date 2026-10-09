#!/usr/bin/env python3
"""Coworker Agent Runtime Evaluation Harness.

Runs evaluation scenarios with an AgentLoop runner and an LLM-as-a-judge,
measuring routing accuracy, duration, token cost, review revisions, and rubric quality.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

if hasattr(sys.stdout, "reconfigure"):
    # line_buffering: progress must reach a redirected log file as it happens (the first v2 run
    # was stopped with nothing but stderr captured).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from nanobot.coworker.config import (
    CoworkerConfig,
    RoomAgentConfig,
    RoomConfig,
    load_coworker_config,
    set_coworker_config_override,
)
from nanobot.coworker.persona import set_persona_id
from nanobot.coworker.room import scheduler
from nanobot.coworker.runtime import turn_running_since
from nanobot.coworker.transcript import content_text
from nanobot.llm_usage import get_llm_usage_store
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIOS_DIR = REPO_ROOT / "tests" / "coworker" / "eval" / "scenarios"
# Finished eval results live in the plans archive; the committed Phase 0 baseline is there and must never be overwritten.
EVAL_RESULTS_DIR = REPO_ROOT / "docs" / "coworker" / "plans" / "archive" / "eval"
PROTECTED_OUTPUTS = (
    EVAL_RESULTS_DIR / "agent-runtime-baseline.json",
    EVAL_RESULTS_DIR / "coworker-eval-baseline.json",
)
DEFAULT_DRYRUN_OUTPUT = EVAL_RESULTS_DIR / "agent-runtime-baseline-dryrun.json"

JUDGE_SYSTEM_PROMPT = (
    "You are an impartial evaluator of AI multi-agent runs. You have no tools and take no actions. "
    "Reply with exactly one JSON object and nothing else."
)
JUDGE_MAX_TOKENS = 4096
# Seconds the room, the coordinator review turn and the inbound queue must all stay idle.
SETTLE_QUIET_PERIOD_S = 3.0


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return "unknown"


def get_git_dirty() -> bool | None:
    """Whether the working tree differs from HEAD; a dirty run is not reproducible from its commit."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], stderr=subprocess.DEVNULL
        )
        return bool(out.strip())
    except Exception:
        return None


class UsageMeter:
    """In-process LLM usage accumulator.

    The shared ``llm_usage.sqlite3`` is written by every nanobot process (a running gateway
    included) and has no session column, so a delta over it cannot be attributed to one run.
    This meter is fed only by the providers the harness builds, which also covers the advisor
    and teammate providers that a per-loop observer would miss.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.reported_tokens = 0
        self.estimated_tokens = 0
        self.by_model: dict[str, dict[str, int]] = {}

    def record(self, call: Any) -> None:
        usage = getattr(call, "usage", None)
        self.calls += 1
        values = {
            "calls": 1,
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            "reported_tokens": int(getattr(usage, "reported_tokens", 0) or 0),
            "estimated_tokens": int(getattr(usage, "estimated_tokens", 0) or 0),
        }
        self.input_tokens += values["input_tokens"]
        self.output_tokens += values["output_tokens"]
        self.total_tokens += values["total_tokens"]
        self.reported_tokens += values["reported_tokens"]
        self.estimated_tokens += values["estimated_tokens"]
        bucket = self.by_model.setdefault(
            f"{getattr(call, 'provider', '?')}/{getattr(call, 'model', '?')}",
            dict.fromkeys(values, 0),
        )
        for key, value in values.items():
            bucket[key] += value

    def totals(self) -> tuple[int, int, int, int, int]:
        return (
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.reported_tokens,
            self.estimated_tokens,
        )


def get_last_llm_call_id() -> int:
    try:
        store = get_llm_usage_store()
        cur = store._connect().execute("SELECT COALESCE(MAX(id), 0) FROM llm_calls")
        row = cur.fetchone()
        if row:
            return int(row[0])
    except Exception as exc:
        print(f"Warning: could not get max llm_calls id: {exc}", file=sys.stderr)
    return 0


def get_tokens_since_id(
    start_id: int, store: Any | None = None
) -> tuple[int, int, int, int, int]:
    try:
        resolved_store = store or get_llm_usage_store()
        cur = resolved_store._connect().execute(
            "SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
            "COALESCE(SUM(total_tokens), 0), COALESCE(SUM(reported_tokens), 0), "
            "COALESCE(SUM(estimated_tokens), 0) "
            "FROM llm_calls WHERE id > ?",
            (start_id,),
        )
        row = cur.fetchone()
        if row:
            return int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4])
    except Exception as exc:
        print(f"Warning: could not query token delta: {exc}", file=sys.stderr)
    return 0, 0, 0, 0, 0


async def wait_room_settled(
    session_key: str,
    timeout: float = 90.0,
    poll_interval: float = 0.5,
    *,
    extra_busy: Callable[[], bool] | None = None,
    quiet_period: float | None = None,
) -> bool:
    """Poll until in-flight delegations and chained turns have completely settled.

    ``extra_busy`` lets the caller report work the room snapshot cannot see: the coordinator's
    ``[auto-room]`` review turn is injected through the bus after the room task has already
    finished, so without it the room looks idle while the review has not started or is running.
    ``quiet_period`` is how long everything must stay idle before the run counts as settled
    (default: one ``poll_interval``).

    Returns True if settled cleanly within timeout, False if timed out.
    """

    def _busy() -> bool:
        return room_busy(session_key) or bool(extra_busy and extra_busy())

    quiet = poll_interval if quiet_period is None else quiet_period
    poll_start = time.monotonic()
    while time.monotonic() - poll_start < timeout:
        if not _busy():
            await asyncio.sleep(quiet)
            if not _busy():
                return True
        else:
            await asyncio.sleep(poll_interval)
    return False


def room_busy(session_key: str) -> bool:
    """True while the room has an active, queued or running teammate run."""
    snap = scheduler.room_snapshot(session_key)
    room = scheduler._rooms.get(scheduler.room_id_for(session_key))
    return bool(snap.active or snap.queued or (room and room.task and not room.task.done()))


async def wait_for_review(
    session_key: str,
    messages_of: Callable[[], list[dict[str, Any]]],
    bus: Any,
    timeout: float,
    poll_interval: float = 0.25,
    quiet_period: float = SETTLE_QUIET_PERIOD_S,
) -> bool:
    """Wait for the coordinator's ``[auto-room]`` review to post its final reply.

    Stage 2 of the wait. Teammate time is already spent when this starts, so the review gets its own
    budget instead of sharing the teammate budget. A chained delegation from the review keeps the
    room busy and restarts the quiet period. Returns False if no final reply appears in time.
    """

    def _busy() -> bool:
        return room_busy(session_key) or turn_pending(session_key, bus)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if review_status(messages_of())[1] and not _busy():
            await asyncio.sleep(quiet_period)
            if review_status(messages_of())[1] and not _busy():
                return True
        await asyncio.sleep(poll_interval)
    return False


def remove_scratch_sessions(sessions_dir: Path | None, workspace: Path) -> bool:
    """Delete the session namespace a scratch workspace created under the real data dir.

    Sessions live outside the workspace (``~/.nanobot/sessions/<workspace-id>``); without this each
    isolated run would leave an orphan folder behind. Only removed when its ``.workspace`` marker
    names exactly this scratch directory, so the real workspace's sessions can never match.
    """
    if sessions_dir is None:
        return False
    try:
        marker = (sessions_dir / ".workspace").read_text(encoding="utf-8").strip()
        if Path(marker).resolve() != workspace.resolve():
            return False
    except (OSError, ValueError):
        return False
    shutil.rmtree(sessions_dir, ignore_errors=True)
    return True


def turn_pending(session_key: str, bus: Any) -> bool:
    """True while the coordinator is mid-turn or an injected turn is still queued on the bus.

    ``MessageBus.inbound_size`` is a property, not a method.
    """
    return turn_running_since(session_key) is not None or bus.inbound_size > 0


def advisor_activity(messages: list[dict[str, Any]]) -> tuple[int, int, int]:
    """(advisor tool calls, successful consults, harness review nudges) found in the session.

    Read from the session, not the logs: a run with zero consults must show zero here even when
    the advisor was enabled, which is the failure this counter exists to expose.
    """
    from nanobot.coworker.advisor.policy import ADVISOR_REVIEW_MARKER

    calls = ok = nudges = 0
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            for call in message.get("tool_calls") or []:
                fn = call.get("function") if isinstance(call, dict) else None
                if isinstance(fn, dict) and fn.get("name") == "advisor":
                    calls += 1
        elif role == "tool" and message.get("name") == "advisor":
            if content_text(message.get("content")).lstrip().startswith("ADVISOR ("):
                ok += 1
        elif role == "user" and ADVISOR_REVIEW_MARKER in content_text(message.get("content")):
            nudges += 1
    return calls, ok, nudges


def extract_final_output(messages: list[dict[str, Any]]) -> str:
    """The coordinator's last plain-text reply: the consolidated report after review, if any."""
    for message in reversed(messages):
        if message.get("role") != "assistant" or message.get("tool_calls"):
            continue
        text = content_text(message.get("content")).strip()
        if text:
            return text
    return ""


def review_status(messages: list[dict[str, Any]]) -> tuple[bool, bool]:
    """(review turn injected, review turn produced a final reply) from the session messages."""
    marker = -1
    for index, message in enumerate(messages):
        if message.get("role") == "user" and "[auto-room]" in content_text(message.get("content")):
            marker = index
    if marker < 0:
        return False, False
    for message in messages[marker + 1:]:
        if message.get("role") == "assistant" and not message.get("tool_calls"):
            if content_text(message.get("content")).strip():
                return True, True
    return True, False


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:12]


def extract_delegations_and_revisions(messages: list[dict[str, Any]]) -> tuple[list[str], int]:
    """Parse room delegations and count revisions issued during review turns."""
    delegations: list[str] = []
    revisions = 0
    in_review_phase = False

    for m in messages:
        role = m.get("role")
        content = str(m.get("content", ""))
        if role == "user" and "[auto-room]" in content:
            in_review_phase = True

        if role == "assistant":
            tool_calls = m.get("tool_calls") or []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function")
                name = fn.get("name") if isinstance(fn, dict) else tc.get("name")
                if name == "room_delegate":
                    args = fn.get("arguments") if isinstance(fn, dict) else tc.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if isinstance(args, dict):
                        target = str(args.get("agent", "")).strip().lstrip("@").lower()
                        if target:
                            delegations.append(target)
                            if in_review_phase:
                                revisions += 1

    return delegations, revisions


@dataclass
class ScenarioRunResult:
    run_idx: int
    duration_s: float
    tokens_in: int
    tokens_out: int
    total_tokens: int
    reported_tokens: int
    estimated_tokens: int
    delegations: list[str]
    routing_accuracy: float
    revision_count: int
    quality_score: float
    criteria_scores: dict[str, float]
    constraint_violations: list[str]
    judge_reasoning: str
    content: str
    timed_out: bool = False
    specialist_outputs: str = ""
    judge_error: str = ""
    # ``content`` stays the coordinator's first-turn reply (the hand-off); the judge grades this.
    final_output: str = ""
    review_injected: bool = False
    review_completed: bool = False
    calls: int = 0
    tokens_by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    workspace: str = ""
    run_error: str = ""
    # Teammate/room tasks cancelled at the end of this run; non-zero means the run was cut short.
    room_tasks_stopped: int = 0
    # Stage timings: teammates (stage 1, budget room_timeout) and coordinator review (stage 2, budget review_timeout).
    teammate_wait_s: float = 0.0
    review_wait_s: float = 0.0
    # Advisor activity in the session (see advisor_activity).
    advisor_calls: int = 0
    advisor_ok: int = 0
    advisor_nudges: int = 0
    # Provider incidents during this run (from the log, so the agent itself is not charged for them).
    provider_retries: int = 0
    provider_gave_up: int = 0
    malformed_responses: int = 0
    connection_errors: int = 0


class ProviderIncidentCounter:
    """Loguru sink that counts provider retries and give-ups while one run is in progress.

    Gemini's ``MALFORMED_FUNCTION_CALL`` and connection errors were the largest source of unexplained
    latency in the first v2 attempt; counting them per run separates provider instability from agent
    behaviour when results are compared.
    """

    def __init__(self) -> None:
        self.retries = 0
        self.gave_up = 0
        self.malformed = 0
        self.connection = 0

    def __call__(self, message: Any) -> None:
        text = str(message.record["message"]).lower()
        # Order matters: a retry line also quotes the malformed reason, so check it first.
        if "llm transient error" in text:
            self.retries += 1
            if "connection error" in text:
                self.connection += 1
        elif "stream ended with finishreason=malformed" in text:
            self.malformed += 1
        elif "llm request failed after" in text:
            self.gave_up += 1

    def apply(self, result: ScenarioRunResult) -> ScenarioRunResult:
        result.provider_retries = self.retries
        result.provider_gave_up = self.gave_up
        result.malformed_responses = self.malformed
        result.connection_errors = self.connection
        return result


async def stop_room_tasks(session_key: str) -> int:
    """Cancel the room run and every teammate turn it started, then wait until they have ended.

    Cancelling only the coordinator's agent loop leaves ``_run_room`` running in the background: its
    teammates keep spending tokens and writing into the room that the next run reuses. Cancelling the
    room task runs its ``finally`` block, which cancels the teammate tasks. Returns 1 if a room task
    was still alive, 0 otherwise.
    """
    room = scheduler._rooms.get(scheduler.room_id_for(session_key))
    stopped = 0
    if room is not None and room.task is not None and not room.task.done():
        stopped = 1
        room.task.cancel()
        await asyncio.gather(room.task, return_exceptions=True)
    scheduler.clear_room(session_key)
    return stopped


def run_result_from_dict(raw: dict[str, Any]) -> ScenarioRunResult:
    """Rebuild a result from a checkpoint line, ignoring keys this version does not know."""
    known = {f for f in ScenarioRunResult.__dataclass_fields__}
    return ScenarioRunResult(**{k: v for k, v in raw.items() if k in known})


class RunLog:
    """Append-only JSONL checkpoint: every finished run is on disk before the next one starts.

    The aggregate JSON is only written at the very end, so a run stopped halfway (as happened to
    the first v2 attempt) used to lose everything. ``arm`` pins runner/judge/advisor so a resume can
    never mix results from a different configuration.
    """

    def __init__(self, path: Path, arm: dict[str, Any]) -> None:
        self.path = path
        self.arm = arm

    @staticmethod
    def reusable(result: dict[str, Any]) -> bool:
        """A checkpointed run is reused only if it finished cleanly.

        A timed-out run or one whose coordinator review never completed is incomplete: its
        judge score is not a measurement of the system, so resume must run it again.
        """
        if result.get("run_error") or result.get("judge_error") or result.get("timed_out"):
            return False
        if result.get("delegations") and not result.get("review_completed"):
            return False
        return True

    def load(self) -> dict[tuple[str, int, str], dict[str, Any]]:
        out: dict[tuple[str, int, str], dict[str, Any]] = {}
        if not self.path.is_file():
            return out
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue  # a torn last line from a killed process
            if not isinstance(row, dict) or row.get("arm") != self.arm:
                continue
            result = row.get("result")
            if isinstance(result, dict) and self.reusable(result):
                out[(str(row.get("scenario_id")), int(row.get("run_idx", 0)), str(row.get("file_hash")))] = result
        return out

    def append(self, scenario_id: str, run_idx: int, file_hash: str, result: ScenarioRunResult) -> None:
        import os

        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "scenario_id": scenario_id,
            "run_idx": run_idx,
            "file_hash": file_hash,
            "arm": self.arm,
            "result": asdict(result),
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


@dataclass
class ScenarioSummary:
    scenario_id: str
    title: str
    file_hash: str
    runs_count: int
    median_duration_s: float
    median_tokens_in: int
    median_tokens_out: int
    median_total_tokens: int
    median_reported_tokens: int
    median_estimated_tokens: int
    mean_routing_accuracy: float
    mean_revision_count: float
    mean_quality_score: float
    total_constraint_violations: int
    judge_error_count: int = 0
    timed_out_count: int = 0
    # Runs that delegated to a teammate but whose coordinator review turn never produced a reply.
    review_incomplete_count: int = 0
    runs: list[dict[str, Any]] = field(default_factory=list)


class CoworkerEvaluator:
    def __init__(
        self,
        scenarios_dir: Path | None = None,
        runner_preset: str = "gemini-3.8-flash-tiered",
        judge_preset: str = "claude-opus-5-5",
        advisor_preset: str | None = None,
        dry_run: bool = False,
        room_timeout: float = 300.0,
        review_timeout: float = 600.0,
        use_real_workspace: bool = False,
        keep_workspace: bool = False,
        run_log: RunLog | None = None,
        resume: bool = False,
        label: str = "",
    ) -> None:
        self.label = label
        self.run_log = run_log
        self.resume = resume
        self.room_timeout = room_timeout
        self.review_timeout = review_timeout
        self.scenarios_dir = scenarios_dir or DEFAULT_SCENARIOS_DIR
        self.runner_preset = runner_preset
        self.judge_preset = judge_preset
        self.advisor_preset = advisor_preset
        self.dry_run = dry_run
        self.use_real_workspace = use_real_workspace
        self.keep_workspace = keep_workspace
        self.meter = UsageMeter()
        self._patcher_port: int | None = None
        self._run_workspace: Path | None = None
        self._judge_runtime: Any = None

    def _get_patcher_port(self) -> int:
        if self._patcher_port is None:
            import socket

            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                self._patcher_port = s.getsockname()[1]
        return self._patcher_port

    def _eval_config(self) -> Any:
        """The user's config with env refs resolved, the patcher moved to a free port, and the
        workspace redirected to the per-run scratch directory (unless ``use_real_workspace``)."""
        from nanobot.config.loader import load_config, resolve_config_env_vars

        config = load_config()
        if (
            config.providers.anthropic_oauth
            and config.providers.anthropic_oauth.patcher
            and config.providers.anthropic_oauth.patcher.enabled
        ):
            config.providers.anthropic_oauth.patcher.port = self._get_patcher_port()
        cfg = resolve_config_env_vars(config)
        if self._run_workspace is not None and not self.use_real_workspace:
            cfg.agents.defaults.workspace = str(self._run_workspace)
        return cfg

    def _make_bot(self) -> Any:
        from nanobot.agent.hooks import create_file_edit_activity_hook
        from nanobot.agent.loop import AgentLoop
        from nanobot.agent.tools.mcp import MCPProvider
        from nanobot.agent.tools.registry import ToolRegistry
        from nanobot.nanobot import Nanobot
        from nanobot.providers.factory import build_provider_snapshot
        from nanobot.providers.image_generation import image_gen_provider_configs

        cfg = self._eval_config()
        tools = ToolRegistry()
        mcp_provider = MCPProvider.from_config(cfg, tools)
        meter = self.meter

        def snapshot_loader(*args: Any, **kwargs: Any) -> Any:
            # Advisor and teammate providers come from here, not from ``loop.provider``.
            snapshot = build_provider_snapshot(cfg, *args, **kwargs)
            if hasattr(snapshot.provider, "set_llm_call_observer"):
                snapshot.provider.set_llm_call_observer(meter.record)
            return snapshot

        loop = AgentLoop.from_config(
            cfg,
            image_generation_provider_configs=image_gen_provider_configs(cfg),
            hook_factories=[create_file_edit_activity_hook],
            tool_registry=tools,
            provider_snapshot_loader=snapshot_loader,
        )
        if hasattr(loop.provider, "set_llm_call_observer"):
            loop.provider.set_llm_call_observer(meter.record)

        return Nanobot(loop, config=cfg, mcp_provider=mcp_provider)

    def preflight(self) -> list[str]:
        """Offline readiness check: no LLM request is made. Returns a list of problems."""
        from nanobot.providers.factory import build_provider_snapshot

        problems: list[str] = []
        scenarios = self.load_scenarios()
        if not scenarios:
            problems.append(f"no scenarios found in {self.scenarios_dir}")
        for sc in scenarios:
            for key in ("prompt", "rubric"):
                if not sc.get(key):
                    problems.append(f"scenario {sc['id']}: missing `{key}`")
            # Absent/empty is valid: a persona scenario expects no delegation (routing accuracy 1.0).
            expected = sc.get("expected_agents", [])
            if not isinstance(expected, list):
                problems.append(f"scenario {sc['id']}: `expected_agents` must be a list")
            for raw in sc.get("room_agents", []) or []:
                try:
                    RoomAgentConfig(**raw)
                except Exception as exc:
                    problems.append(f"scenario {sc['id']}: invalid room agent {raw.get('id')!r}: {exc}")
        try:
            cfg = self._eval_config()
        except Exception as exc:
            return [*problems, f"cannot load nanobot config: {type(exc).__name__}: {exc}"]
        roles = {"runner": self.runner_preset, "judge": self.judge_preset}
        advisor = self.advisor_preset or load_coworker_config().advisor.preset
        if advisor and advisor != "off":
            roles["advisor"] = advisor
        for role, preset in roles.items():
            try:
                build_provider_snapshot(cfg, preset_name=preset)
            except Exception as exc:
                problems.append(f"{role} preset {preset!r}: {type(exc).__name__}: {exc}")
        if advisor in (None, ""):
            problems.append(
                "no advisor preset configured and --advisor-preset not given: pass "
                "`--advisor-preset <preset>` for the advisor-on arm or `off` for the control arm"
            )
        return problems

    def load_scenarios(self, scenario_slug: str | None = None) -> list[dict[str, Any]]:
        yaml_files = sorted(self.scenarios_dir.glob("*.yaml"))
        scenarios: list[dict[str, Any]] = []
        for f in yaml_files:
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                sid = data.get("id") or f.stem
                data["id"] = sid
                data["_file_path"] = f
                data["_file_hash"] = hash_file(f)
                if scenario_slug and sid != scenario_slug:
                    continue
                scenarios.append(data)
            except Exception as exc:
                print(f"Error loading scenario {f}: {exc}", file=sys.stderr)
        return scenarios

    async def _judge_eval(
        self,
        scenario: dict[str, Any],
        transcript_content: str,
        delegations: list[str],
        specialist_outputs: str = "",
        final_output: str = "",
    ) -> tuple[float, dict[str, float], list[str], str, str]:
        """Return (overall, scores, violations, reasoning, judge_error).

        ``judge_error`` is non-empty when the judge output could not be parsed even after
        one retry; such runs must be excluded from quality means (no 3.0 default).
        """
        if self.dry_run:
            rubric = scenario.get("rubric", {})
            criteria = rubric.get("criteria", [])
            scores = {c["name"]: 5.0 for c in criteria if isinstance(c, dict)}
            return 5.0, scores, [], "Dry-run synthetic evaluation (all criteria passed).", ""

        judge_prompt = self._build_judge_prompt(
            scenario, transcript_content, delegations, specialist_outputs, final_output
        )
        last: tuple[float, dict[str, float], list[str], str, str] = (
            0.0, {}, [], "", "judge not run"
        )
        for _attempt in (1, 2):
            try:
                raw = await self._judge_call(judge_prompt)
            except Exception as exc:
                last = (0.0, {}, [], "", f"judge call failed: {type(exc).__name__}: {exc}")
                continue
            last = self._parse_judge_response(raw)
            if not last[4]:
                return last
        return last

    async def _judge_call(self, prompt: str) -> str:
        """One tool-less completion on the judge preset.

        The judge must not run inside an ``AgentLoop``: that gives it the advisor tool, memory and
        a persona-less system prompt, and its wrapper prose is what broke parsing in the first baseline.
        """
        from nanobot.providers.factory import build_provider_snapshot
        from nanobot.utils.llm_runtime import runtime_from_provider_snapshot

        if self._judge_runtime is None:
            snapshot = build_provider_snapshot(self._eval_config(), preset_name=self.judge_preset)
            self._judge_runtime = runtime_from_provider_snapshot(snapshot)
        runtime = self._judge_runtime
        response = await runtime.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            model=runtime.model,
            max_tokens=JUDGE_MAX_TOKENS,
        )
        if response.finish_reason == "error" or not (response.content or "").strip():
            raise RuntimeError(f"judge returned no usable answer (finish_reason={response.finish_reason})")
        return str(response.content)

    def _build_judge_prompt(
        self,
        scenario: dict[str, Any],
        transcript_content: str,
        delegations: list[str],
        specialist_outputs: str = "",
        final_output: str = "",
    ) -> str:
        specialist_block = specialist_outputs.strip() or "(no specialist replies were recorded)"
        final_block = final_output.strip() or "(the coordinator posted no report after the review turn)"
        rubric_text = json.dumps(scenario.get("rubric", {}), ensure_ascii=False, indent=2)
        constraints_text = json.dumps(scenario.get("constraints", []), ensure_ascii=False, indent=2)
        expected = json.dumps(scenario.get("expected_agents", []), ensure_ascii=False)
        actual = json.dumps(delegations, ensure_ascii=False)

        return f"""You are an expert impartial evaluator grading an AI multi-agent coworker run.

### Scenario: {scenario.get('title', scenario['id'])}
Prompt:
\"\"\"{scenario.get('prompt', '')}\"\"\"

Expected delegated agents: {expected}
Actual delegated agents: {actual}

### Rubric:
{rubric_text}

### Constraints:
{constraints_text}

### Coordinator hand-off message (first turn, before teammates ran):
\"\"\"{transcript_content}\"\"\"

### Specialist deliverables (room transcript, in order):
\"\"\"{specialist_block}\"\"\"

### Coordinator final report (last reply, after reviewing the teammates):
\"\"\"{final_block}\"\"\"

Grade the deliverables and the final report, not just the hand-off message.

Evaluate the response carefully.
1. Score each rubric criterion on a 1.0 to 5.0 scale (1=fail, 3=acceptable, 5=excellent).
2. Check every constraint in the checklist. If any constraint is violated, list it.
3. Compute an overall quality score between 1.0 and 5.0.
4. Provide concise reasoning.

Respond ONLY with a JSON object matching this schema:
{{
  "scores": {{
    "<criterion_name>": 5.0
  }},
  "overall_score": 5.0,
  "constraint_violations": [],
  "reasoning": "brief justification"
}}
"""

    def _parse_judge_response(
        self,
        raw_text: str,
    ) -> tuple[float, dict[str, float], list[str], str, str]:
        text = raw_text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        def _try(candidate: str) -> dict[str, Any] | None:
            try:
                obj = json.loads(candidate)
            except Exception:
                return None
            return obj if isinstance(obj, dict) and "overall_score" in obj else None

        parsed = _try(text)
        if parsed is None:
            # Tolerate wrapper prose (e.g. advisor notes) around the JSON object.
            decoder = json.JSONDecoder()
            for i, ch in enumerate(raw_text):
                if ch != "{":
                    continue
                try:
                    obj, _ = decoder.raw_decode(raw_text[i:])
                except Exception:
                    continue
                if isinstance(obj, dict) and "overall_score" in obj:
                    parsed = obj
                    break
        if parsed is None:
            return 0.0, {}, [], "", f"unparseable judge output. Raw: {raw_text[:300]}"
        try:
            overall = float(parsed["overall_score"])
            scores = {str(k): float(v) for k, v in (parsed.get("scores") or {}).items()}
            violations = [str(x) for x in parsed.get("constraint_violations", [])]
            reasoning = str(parsed.get("reasoning", ""))
        except Exception as exc:
            return 0.0, {}, [], "", f"invalid judge fields: {exc}. Raw: {raw_text[:300]}"
        return overall, scores, violations, reasoning, ""

    async def run_scenario_once(
        self,
        scenario: dict[str, Any],
        run_idx: int,
    ) -> ScenarioRunResult:
        sid = scenario["id"]
        session_key = f"eval:{sid}:run{run_idx}_{int(time.time())}"
        expected_agents = [str(a).lower() for a in scenario.get("expected_agents", [])]

        if self.dry_run:
            duration = 0.1
            tin, tout, ttot, trep, test = 120, 45, 165, 165, 0
            delegations = list(expected_agents)
            routing_acc = 1.0
            rev_count = 0
            quality, criteria_scores, violations, reasoning, judge_error = await self._judge_eval(
                scenario, "Dry run transcript mock output.", delegations
            )
            return ScenarioRunResult(
                run_idx=run_idx,
                duration_s=duration,
                tokens_in=tin,
                tokens_out=tout,
                total_tokens=ttot,
                reported_tokens=trep,
                estimated_tokens=test,
                delegations=delegations,
                routing_accuracy=routing_acc,
                revision_count=rev_count,
                quality_score=quality,
                criteria_scores=criteria_scores,
                constraint_violations=violations,
                judge_reasoning=reasoning,
                content="[Dry run output]",
                judge_error=judge_error,
                review_injected=bool(delegations),
                review_completed=True,
            )


        # Configure room agents for this scenario
        base_cfg = load_coworker_config()
        room_agents_data = scenario.get("room_agents", [])
        agents_list = [
            RoomAgentConfig(**a) for a in room_agents_data
        ] if room_agents_data else base_cfg.room.agents

        advisor_cfg = (
            base_cfg.advisor.model_copy(update={"preset": self.advisor_preset})
            if self.advisor_preset
            else base_cfg.advisor
        )
        eval_cfg = CoworkerConfig(
            advisor=advisor_cfg,
            room=RoomConfig(
                enabled=True,
                agents=agents_list,
                max_chained_turns=base_cfg.room.max_chained_turns,
            ),
            coding=base_cfg.coding,
            context=base_cfg.context,
            workflows=base_cfg.workflows,
        )
        set_coworker_config_override(eval_cfg)

        # Fresh scratch workspace per run: no artifacts, sessions or room files leak between runs
        # (or into the user's real workspace / this repo), and room files have a known location.
        run_workspace: Path | None = None
        if not self.use_real_workspace:
            run_workspace = Path(tempfile.mkdtemp(prefix=f"coworker-eval-{sid}-r{run_idx}-")).resolve()
        self._run_workspace = run_workspace
        scratch_sessions_dir: Path | None = None
        self.meter.reset()
        t_start = time.perf_counter()

        transcript = ""
        specialist_outputs = ""
        final_output = ""
        review_injected = False
        review_completed = False
        cleanly_settled = False
        delegations_recorded: list[str] = []
        revision_count = 0
        room_tasks_stopped = 0
        teammate_wait_s = 0.0
        review_wait_s = 0.0
        advisor_calls = advisor_ok = advisor_nudges = 0
        incidents = ProviderIncidentCounter()
        sink_id = logger.add(incidents, level="WARNING")
        loop_task: asyncio.Task[Any] | None = None

        try:
            async with self._make_bot() as bot:
                # Start background AgentLoop to process review turns from MessageBus
                loop_task = asyncio.create_task(bot._loop.run())
                if run_workspace is not None:
                    scratch_sessions_dir = getattr(bot._loop.sessions, "sessions_dir", None)

                session = bot._loop.sessions.get_or_create(session_key)
                session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = self.runner_preset

                persona_id = scenario.get("persona")
                if persona_id:
                    set_persona_id(session, persona_id, eval_cfg)
                elif agents_list:
                    # Explicitly arm multi-agent room
                    scheduler.set_armed(session, True)

                # Send user prompt
                prompt = scenario.get("prompt", "")
                result = await bot.run(prompt, session_key=session_key)
                transcript = result.content

                # Stage 1: teammates. Room-only busy check. The review turn is injected before the
                # room task ends, so when this returns the review is already queued or running.
                loop_bus = bot._loop.bus
                t_stage = time.perf_counter()
                teammates_settled = await wait_room_settled(
                    session_key,
                    timeout=self.room_timeout,
                    quiet_period=SETTLE_QUIET_PERIOD_S,
                )
                teammate_wait_s = round(time.perf_counter() - t_stage, 2)

                # Stage 2: the coordinator's review, with its own budget. Only needed when a
                # teammate was delegated to; teammates that did not finish cannot be reviewed.
                needs_review = bool(extract_delegations_and_revisions(session.messages)[0])
                t_stage = time.perf_counter()
                if not teammates_settled:
                    review_settled = False
                elif not needs_review:
                    review_settled = True
                else:
                    review_settled = await wait_for_review(
                        session_key,
                        lambda: session.messages,
                        loop_bus,
                        timeout=self.review_timeout,
                    )
                review_wait_s = round(time.perf_counter() - t_stage, 2)
                cleanly_settled = teammates_settled and review_settled

                # Collect specialist deliverables from the room transcript before teardown
                try:
                    from nanobot.coworker.room.store import RoomTranscript

                    entries = RoomTranscript(
                        scheduler._workspace(), scheduler.room_id_for(session_key)
                    ).entries()
                    specialist_outputs = "\n\n".join(
                        f"[{e.get('speaker')}]\n{e.get('text')}" for e in entries
                    )
                except Exception as exc:
                    specialist_outputs = f"(failed to read room transcript: {exc})"

                # Collect delegations and revisions from session messages
                delegations_recorded, revision_count = extract_delegations_and_revisions(
                    session.messages
                )
                final_output = extract_final_output(session.messages)
                review_injected, review_completed = review_status(session.messages)
                advisor_calls, advisor_ok, advisor_nudges = advisor_activity(session.messages)

                loop_task.cancel()
                try:
                    await loop_task
                except asyncio.CancelledError:
                    pass

        finally:
            # Stop every room task before the next run can start: a timed-out room otherwise keeps
            # running into the next run's room and inflates its time and tokens.
            room_tasks_stopped = await stop_room_tasks(session_key)
            if loop_task is not None and not loop_task.done():
                loop_task.cancel()
            logger.remove(sink_id)
            set_coworker_config_override(None)
            scheduler.reset_rooms()
            self._run_workspace = None
            if run_workspace is not None and not self.keep_workspace:
                remove_scratch_sessions(scratch_sessions_dir, run_workspace)
                shutil.rmtree(run_workspace, ignore_errors=True)

        duration = time.perf_counter() - t_start
        tin, tout, ttot, trep, test = self.meter.totals()

        # Calculate routing accuracy
        if expected_agents:
            matched = len(set(expected_agents) & set(delegations_recorded))
            routing_acc = matched / len(expected_agents)
        else:
            routing_acc = 1.0

        quality, criteria_scores, violations, reasoning, judge_error = await self._judge_eval(
            scenario, transcript, delegations_recorded, specialist_outputs, final_output
        )

        return incidents.apply(ScenarioRunResult(
            run_idx=run_idx,
            duration_s=round(duration, 2),
            tokens_in=tin,
            tokens_out=tout,
            total_tokens=ttot,
            reported_tokens=trep,
            estimated_tokens=test,
            delegations=delegations_recorded,
            routing_accuracy=round(routing_acc, 2),
            revision_count=revision_count,
            quality_score=quality,
            criteria_scores=criteria_scores,
            constraint_violations=violations,
            judge_reasoning=reasoning,
            content=transcript,
            timed_out=not cleanly_settled,
            specialist_outputs=specialist_outputs,
            judge_error=judge_error,
            final_output=final_output,
            review_injected=review_injected,
            review_completed=review_completed,
            calls=self.meter.calls,
            tokens_by_model={k: dict(v) for k, v in self.meter.by_model.items()},
            workspace=str(run_workspace) if run_workspace is not None and self.keep_workspace else "",
            room_tasks_stopped=room_tasks_stopped,
            teammate_wait_s=teammate_wait_s,
            review_wait_s=review_wait_s,
            advisor_calls=advisor_calls,
            advisor_ok=advisor_ok,
            advisor_nudges=advisor_nudges,
        ))

    async def run_scenario(
        self,
        scenario: dict[str, Any],
        num_runs: int = 3,
    ) -> ScenarioSummary:
        sid = scenario["id"]
        title = scenario.get("title", sid)
        fhash = scenario.get("_file_hash", "")
        print(f"\n--- Running scenario: {sid} ({title}) [{num_runs} run(s)] ---")

        previous = self.run_log.load() if (self.run_log and self.resume) else {}
        runs: list[ScenarioRunResult] = []
        for i in range(1, num_runs + 1):
            cached = previous.get((sid, i, fhash))
            if cached is not None:
                runs.append(run_result_from_dict(cached))
                print(f"  Run #{i}... reused from checkpoint", flush=True)
                continue
            print(f"  Run #{i}...", end="", flush=True)
            try:
                run_res = await self.run_scenario_once(scenario, i)
            except Exception as exc:  # one broken run must not discard the rest of the batch
                set_coworker_config_override(None)
                scheduler.reset_rooms()
                run_res = ScenarioRunResult(
                    run_idx=i, duration_s=0.0, tokens_in=0, tokens_out=0, total_tokens=0,
                    reported_tokens=0, estimated_tokens=0, delegations=[], routing_accuracy=0.0,
                    revision_count=0, quality_score=0.0, criteria_scores={}, constraint_violations=[],
                    judge_reasoning="", content="", timed_out=True,
                    judge_error=f"run failed: {type(exc).__name__}: {exc}",
                    run_error=f"{type(exc).__name__}: {exc}",
                )
            runs.append(run_res)
            if self.run_log is not None:
                self.run_log.append(sid, i, fhash, run_res)
            print(f" done ({run_res.duration_s}s, {run_res.total_tokens} tokens, score: {run_res.quality_score}/5"
                  f"{', RUN_ERROR' if run_res.run_error else ''}"
                  f"{', JUDGE_ERROR' if run_res.judge_error and not run_res.run_error else ''}"
                  f"{', TIMED_OUT' if run_res.timed_out and not run_res.run_error else ''}"
                  f"{', REVIEW_INCOMPLETE' if run_res.delegations and not run_res.review_completed else ''})",
                  flush=True)

        measured = [r for r in runs if not r.run_error] or runs  # crashed runs carry no measurements
        durations = sorted(r.duration_s for r in measured)
        tokens_tot = sorted(r.total_tokens for r in measured)
        tokens_in = sorted(r.tokens_in for r in measured)
        tokens_out = sorted(r.tokens_out for r in measured)
        tokens_rep = sorted(r.reported_tokens for r in measured)
        tokens_est = sorted(r.estimated_tokens for r in measured)
        med_idx = len(measured) // 2

        mean_routing = sum(r.routing_accuracy for r in runs) / len(runs)
        mean_rev = sum(r.revision_count for r in runs) / len(runs)
        valid = [r for r in runs if not r.judge_error]
        mean_quality = sum(r.quality_score for r in valid) / len(valid) if valid else 0.0
        total_violations = sum(len(r.constraint_violations) for r in runs)

        return ScenarioSummary(
            scenario_id=sid,
            title=title,
            file_hash=fhash,
            runs_count=len(runs),
            median_duration_s=round(durations[med_idx], 2),
            median_tokens_in=tokens_in[med_idx],
            median_tokens_out=tokens_out[med_idx],
            median_total_tokens=tokens_tot[med_idx],
            median_reported_tokens=tokens_rep[med_idx],
            median_estimated_tokens=tokens_est[med_idx],
            mean_routing_accuracy=round(mean_routing, 2),
            mean_revision_count=round(mean_rev, 2),
            mean_quality_score=round(mean_quality, 2),
            total_constraint_violations=total_violations,
            judge_error_count=len(runs) - len(valid),
            timed_out_count=sum(1 for r in runs if r.timed_out),
            review_incomplete_count=sum(
                1 for r in runs if r.delegations and not r.review_completed and not r.run_error
            ),
            runs=[asdict(r) for r in runs],
        )

    async def run_all(
        self,
        scenario_slug: str | None = None,
        num_runs: int = 3,
    ) -> dict[str, Any]:
        scenarios = self.load_scenarios(scenario_slug)
        if not scenarios:
            raise ValueError(f"No scenarios found in {self.scenarios_dir} (filter: {scenario_slug})")

        summaries: dict[str, ScenarioSummary] = {}
        for sc in scenarios:
            summary = await self.run_scenario(sc, num_runs)
            summaries[sc["id"]] = summary

        all_durations = [s.median_duration_s for s in summaries.values()]
        all_tokens = [s.median_total_tokens for s in summaries.values()]
        all_quality = [
            s.mean_quality_score
            for s in summaries.values()
            if s.judge_error_count < s.runs_count
        ] or [0.0]
        all_routing = [s.mean_routing_accuracy for s in summaries.values()]

        effective_advisor = load_coworker_config().advisor.model_copy(
            update={"preset": self.advisor_preset} if self.advisor_preset else {}
        )
        payload = {
            "metadata": {
                "git_commit": get_git_commit(),
                "git_dirty": get_git_dirty(),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "platform": f"{platform.system()} {platform.machine()}",
                "runner_preset": self.runner_preset,
                "judge_preset": self.judge_preset,
                "advisor_preset": self.advisor_preset or "default",
                "advisor_config": effective_advisor.model_dump(),
                "dry_run": self.dry_run,
                "phase": "Phase 0 Baseline v2",
                "label": self.label,
                "room_timeout_s": self.room_timeout,
                "review_timeout_s": self.review_timeout,
                "workspace_mode": "real" if self.use_real_workspace else "isolated-temp-per-run",
                "token_source": "in-process UsageMeter (runner, advisor and teammate providers)",
                "judge_mode": "direct provider call, no tools",
            },
            "scenarios": {k: asdict(v) for k, v in summaries.items()},
            "summary": {
                "total_scenarios": len(summaries),
                "median_duration_s": round(sorted(all_durations)[len(all_durations) // 2], 2),
                "median_total_tokens": sorted(all_tokens)[len(all_tokens) // 2],
                "mean_quality_score": round(sum(all_quality) / len(all_quality), 2),
                "mean_routing_accuracy": round(sum(all_routing) / len(all_routing), 2),
                "judge_error_total": sum(s.judge_error_count for s in summaries.values()),
                "timed_out_total": sum(s.timed_out_count for s in summaries.values()),
                "review_incomplete_total": sum(s.review_incomplete_count for s in summaries.values()),
                "total_runs": sum(s.runs_count for s in summaries.values()),
            },
        }
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Coworker Agent Runtime Evaluation Harness")
    parser.add_argument("--scenario", "-s", type=str, default=None, help="Scenario slug (e.g. edutech-course)")
    parser.add_argument("--runs", "-r", type=int, default=3, help="Number of runs per scenario (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Run with mock provider/judge (no tokens consumed)")
    parser.add_argument("--runner-preset", type=str, default="gemini-3.8-flash-tiered", help="Runner model preset")
    parser.add_argument("--judge-preset", type=str, default="claude-opus-5-5", help="Judge model preset")
    parser.add_argument(
        "--advisor-preset",
        type=str,
        default=None,
        help="Advisor model preset (overrides coworker advisor config preset)",
    )
    parser.add_argument(
        "--room-timeout",
        type=float,
        default=900.0,
        help="Stage 1 budget: seconds for the teammates to finish (default: 900)",
    )
    parser.add_argument(
        "--review-timeout",
        type=float,
        default=600.0,
        help="Stage 2 budget: seconds for the coordinator's review to post its report (default: 600)",
    )
    parser.add_argument(
        "--scenarios-dir",
        type=Path,
        default=None,
        help="Path to scenarios directory",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help=(
            "Path to output JSON file. Required for live runs; an existing file is never overwritten "
            "without --force. Progress is checkpointed next to it as <output>.runs.jsonl"
        ),
    )
    parser.add_argument("--label", type=str, default="", help="Free-text arm label stored in the metadata")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse finished runs from <output>.runs.jsonl (same presets and scenario file only)",
    )
    parser.add_argument("--force", action="store_true", help="Allow overwriting an existing --output file")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Check scenarios, presets and config offline (no LLM request), then exit",
    )
    parser.add_argument(
        "--use-real-workspace",
        action="store_true",
        help="Run inside the configured workspace instead of a scratch directory per run (not recommended)",
    )
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Keep each run's scratch workspace and record its path in the result",
    )

    args = parser.parse_args()

    if args.preflight:
        problems = CoworkerEvaluator(
            scenarios_dir=args.scenarios_dir,
            runner_preset=args.runner_preset,
            judge_preset=args.judge_preset,
            advisor_preset=args.advisor_preset,
        ).preflight()
        if problems:
            print("[PREFLIGHT FAILED]")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("[PREFLIGHT OK] scenarios valid, presets resolve (no LLM request was made)")
        return 0

    output_path = args.output
    if args.dry_run:
        if output_path is None or output_path.resolve() in {p.resolve() for p in PROTECTED_OUTPUTS}:
            if output_path is not None:
                print(f"Refusing to write dry-run data to {output_path}; using the dry-run file.", file=sys.stderr)
            output_path = DEFAULT_DRYRUN_OUTPUT
    else:
        if output_path is None:
            print("--output is required for a live run (pick a new file, e.g. "
                  "docs/coworker/tests/coworker-eval-<label>.json).", file=sys.stderr)
            return 2
        if output_path.resolve() in {p.resolve() for p in PROTECTED_OUTPUTS}:
            print(f"Refusing to write a live run to the protected baseline {output_path}.", file=sys.stderr)
            return 2
        if output_path.exists() and not args.force and not args.resume:
            print(f"{output_path} already exists; use --resume to continue it or --force to overwrite.",
                  file=sys.stderr)
            return 2

    arm = {
        "runner": args.runner_preset,
        "judge": args.judge_preset,
        "advisor": args.advisor_preset or "default",
    }
    run_log = None if args.dry_run else RunLog(output_path.with_name(output_path.name + ".runs.jsonl"), arm)
    evaluator = CoworkerEvaluator(
        scenarios_dir=args.scenarios_dir,
        runner_preset=args.runner_preset,
        judge_preset=args.judge_preset,
        advisor_preset=args.advisor_preset,
        dry_run=args.dry_run,
        room_timeout=args.room_timeout,
        review_timeout=args.review_timeout,
        use_real_workspace=args.use_real_workspace,
        keep_workspace=args.keep_workspace,
        run_log=run_log,
        resume=args.resume,
        label=args.label,
    )

    if not args.dry_run:
        problems = evaluator.preflight()
        if problems:
            print("[PREFLIGHT FAILED] fix these before spending tokens:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1

    payload = asyncio.run(evaluator.run_all(args.scenario, args.runs))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Baseline eval written to {output_path}")
    print(f"Summary: {json.dumps(payload['summary'], indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
