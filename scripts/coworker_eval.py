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
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
from nanobot.llm_usage import get_llm_usage_store
from nanobot.session.model_selection import SESSION_MODEL_PRESET_METADATA_KEY

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIOS_DIR = REPO_ROOT / "tests" / "coworker" / "eval" / "scenarios"
DEFAULT_BASELINE_OUTPUT = REPO_ROOT / "docs" / "coworker" / "plans" / "agent-runtime-baseline.json"
DEFAULT_DRYRUN_OUTPUT = REPO_ROOT / "docs" / "coworker" / "plans" / "agent-runtime-baseline-dryrun.json"


def get_git_commit() -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
        return out.decode("utf-8").strip()
    except Exception:
        return "unknown"


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


async def wait_room_settled(session_key: str, timeout: float = 90.0, poll_interval: float = 0.5) -> bool:
    """Poll until in-flight delegations and chained turns have completely settled.

    Returns True if settled cleanly within timeout, False if timed out.
    """
    poll_start = time.monotonic()
    while time.monotonic() - poll_start < timeout:
        snap = scheduler.room_snapshot(session_key)
        room = scheduler._rooms.get(scheduler.room_id_for(session_key))
        is_busy = bool(snap.active or snap.queued or (room and room.task and not room.task.done()))
        if not is_busy:
            await asyncio.sleep(poll_interval)
            snap2 = scheduler.room_snapshot(session_key)
            if not bool(snap2.active or snap2.queued or (room and room.task and not room.task.done())):
                return True
        await asyncio.sleep(poll_interval)
    return False


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
    runs: list[dict[str, Any]] = field(default_factory=list)


class CoworkerEvaluator:
    def __init__(
        self,
        scenarios_dir: Path | None = None,
        runner_preset: str = "gemini-3.8-flash-tiered",
        judge_preset: str = "claude-opus-5-5",
        dry_run: bool = False,
    ) -> None:
        self.scenarios_dir = scenarios_dir or DEFAULT_SCENARIOS_DIR
        self.runner_preset = runner_preset
        self.judge_preset = judge_preset
        self.dry_run = dry_run

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
    ) -> tuple[float, dict[str, float], list[str], str]:
        if self.dry_run:
            rubric = scenario.get("rubric", {})
            criteria = rubric.get("criteria", [])
            scores = {c["name"]: 5.0 for c in criteria if isinstance(c, dict)}
            return 5.0, scores, [], "Dry-run synthetic evaluation (all criteria passed)."

        from nanobot.nanobot import Nanobot

        judge_prompt = self._build_judge_prompt(scenario, transcript_content, delegations)
        async with Nanobot.from_config() as bot:
            session = bot.sessions.get_or_create(f"eval:judge:{scenario['id']}:{time.time()}")
            session.metadata[SESSION_MODEL_PRESET_METADATA_KEY] = self.judge_preset
            res = await bot.run(judge_prompt, session_key=session.key)

        return self._parse_judge_response(res.content)

    def _build_judge_prompt(
        self,
        scenario: dict[str, Any],
        transcript_content: str,
        delegations: list[str],
    ) -> str:
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

### Run Transcript & Output:
\"\"\"{transcript_content}\"\"\"

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
    ) -> tuple[float, dict[str, float], list[str], str]:
        text = raw_text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            parsed = json.loads(text)
            overall = float(parsed.get("overall_score", 3.0))
            scores = {str(k): float(v) for k, v in parsed.get("scores", {}).items()}
            violations = [str(x) for x in parsed.get("constraint_violations", [])]
            reasoning = str(parsed.get("reasoning", ""))
            return overall, scores, violations, reasoning
        except Exception as exc:
            return 3.0, {}, [], f"Failed to parse judge output: {exc}. Raw: {raw_text[:200]}"

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
            quality, criteria_scores, violations, reasoning = await self._judge_eval(
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
            )

        from nanobot.nanobot import Nanobot

        # Configure room agents for this scenario
        base_cfg = load_coworker_config()
        room_agents_data = scenario.get("room_agents", [])
        agents_list = [
            RoomAgentConfig(**a) for a in room_agents_data
        ] if room_agents_data else base_cfg.room.agents

        eval_cfg = CoworkerConfig(
            advisor=base_cfg.advisor,
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

        start_call_id = get_last_llm_call_id()
        t_start = time.perf_counter()

        transcript = ""
        delegations_recorded: list[str] = []
        revision_count = 0

        try:
            async with Nanobot.from_config() as bot:
                # Start background AgentLoop to process review turns from MessageBus
                loop_task = asyncio.create_task(bot._loop.run())

                session = bot.sessions.get_or_create(session_key)
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

                # Wait for chained room runs and coordinator review turns to settle
                cleanly_settled = await wait_room_settled(session_key)

                # Collect delegations and revisions from session messages
                delegations_recorded, revision_count = extract_delegations_and_revisions(
                    session.messages
                )

                loop_task.cancel()
                try:
                    await loop_task
                except asyncio.CancelledError:
                    pass

        finally:
            set_coworker_config_override(None)
            scheduler.reset_rooms()

        duration = time.perf_counter() - t_start
        tin, tout, ttot, trep, test = get_tokens_since_id(start_call_id)

        # Calculate routing accuracy
        if expected_agents:
            matched = len(set(expected_agents) & set(delegations_recorded))
            routing_acc = matched / len(expected_agents)
        else:
            routing_acc = 1.0

        quality, criteria_scores, violations, reasoning = await self._judge_eval(
            scenario, transcript, delegations_recorded
        )

        return ScenarioRunResult(
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
        )

    async def run_scenario(
        self,
        scenario: dict[str, Any],
        num_runs: int = 3,
    ) -> ScenarioSummary:
        sid = scenario["id"]
        title = scenario.get("title", sid)
        fhash = scenario.get("_file_hash", "")
        print(f"\n--- Running scenario: {sid} ({title}) [{num_runs} run(s)] ---")

        runs: list[ScenarioRunResult] = []
        for i in range(1, num_runs + 1):
            print(f"  Run #{i}...", end="", flush=True)
            run_res = await self.run_scenario_once(scenario, i)
            runs.append(run_res)
            print(f" done ({run_res.duration_s}s, {run_res.total_tokens} tokens, score: {run_res.quality_score}/5)")

        durations = sorted(r.duration_s for r in runs)
        tokens_tot = sorted(r.total_tokens for r in runs)
        tokens_in = sorted(r.tokens_in for r in runs)
        tokens_out = sorted(r.tokens_out for r in runs)
        tokens_rep = sorted(r.reported_tokens for r in runs)
        tokens_est = sorted(r.estimated_tokens for r in runs)
        med_idx = len(runs) // 2

        mean_routing = sum(r.routing_accuracy for r in runs) / len(runs)
        mean_rev = sum(r.revision_count for r in runs) / len(runs)
        mean_quality = sum(r.quality_score for r in runs) / len(runs)
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
        all_quality = [s.mean_quality_score for s in summaries.values()]
        all_routing = [s.mean_routing_accuracy for s in summaries.values()]

        payload = {
            "metadata": {
                "git_commit": get_git_commit(),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "platform": f"{platform.system()} {platform.machine()}",
                "runner_preset": self.runner_preset,
                "judge_preset": self.judge_preset,
                "dry_run": self.dry_run,
                "phase": "Phase 0 Baseline",
            },
            "scenarios": {k: asdict(v) for k, v in summaries.items()},
            "summary": {
                "total_scenarios": len(summaries),
                "median_duration_s": round(sorted(all_durations)[len(all_durations) // 2], 2),
                "median_total_tokens": sorted(all_tokens)[len(all_tokens) // 2],
                "mean_quality_score": round(sum(all_quality) / len(all_quality), 2),
                "mean_routing_accuracy": round(sum(all_routing) / len(all_routing), 2),
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
        help="Path to output JSON file",
    )

    args = parser.parse_args()

    output_path = args.output
    if output_path is None:
        output_path = DEFAULT_DRYRUN_OUTPUT if args.dry_run else DEFAULT_BASELINE_OUTPUT
    elif args.dry_run and output_path.resolve() == DEFAULT_BASELINE_OUTPUT.resolve():
        print(
            "Refusing to write dry-run data to live baseline file: "
            f"{DEFAULT_BASELINE_OUTPUT}. Using dry-run file instead.",
            file=sys.stderr,
        )
        output_path = DEFAULT_DRYRUN_OUTPUT

    evaluator = CoworkerEvaluator(
        scenarios_dir=args.scenarios_dir,
        runner_preset=args.runner_preset,
        judge_preset=args.judge_preset,
        dry_run=args.dry_run,
    )

    payload = asyncio.run(evaluator.run_all(args.scenario, args.runs))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] Baseline eval written to {output_path}")
    print(f"Summary: {json.dumps(payload['summary'], indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
