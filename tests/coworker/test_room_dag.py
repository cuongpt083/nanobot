"""Tests for Phase 4.4 parallel DAG room scheduler."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest

from nanobot.coworker.config import CoworkerConfig, RoomAgentConfig, RoomConfig
from nanobot.coworker.room import scheduler

KEY = "telegram:dag"
OWNER_RUNTIME: Any = SimpleNamespace(model="owner-model")
CTX = "Context for testing parallel DAG execution with adequate length to satisfy min_context_chars requirement."


def _config(max_parallel: int = 1, max_chained: int = 16) -> CoworkerConfig:
    return CoworkerConfig(
        room=RoomConfig(
            agents=[
                RoomAgentConfig(id="agent_a", name="Agent A", bio="alpha"),
                RoomAgentConfig(id="agent_b", name="Agent B", bio="beta"),
                RoomAgentConfig(id="agent_c", name="Agent C", bio="gamma"),
            ],
            max_parallel=max_parallel,
            max_chained_turns=max_chained,
        )
    )


async def _drain(key: str) -> None:
    room = scheduler._room(key)
    assert room.task is not None
    await room.task


@pytest.mark.asyncio
async def test_dag_parallel_execution_overlaps_and_speeds_up(env) -> None:
    """Three independent delegations run concurrently when max_parallel=3."""
    env.configure(_config(max_parallel=3))

    running_concurrent = 0
    max_concurrent = 0

    class ConcurrentSubagents:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def run_inline(self, *, task: str, label: str, **kwargs: Any) -> str:
            nonlocal running_concurrent, max_concurrent
            agent = label.removeprefix("room:")
            running_concurrent += 1
            max_concurrent = max(max_concurrent, running_concurrent)
            self.calls.append((agent, task))
            try:
                await asyncio.sleep(0.08)
                return f"Result from {agent}"
            finally:
                running_concurrent -= 1

    env.subagents = ConcurrentSubagents()
    env.bind()

    t0 = time.monotonic()
    scheduler.record_delegation(KEY, "agent_a", "task 1", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.record_delegation(KEY, "agent_b", "task 2", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.record_delegation(KEY, "agent_c", "task 3", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="dag")
    await _drain(KEY)
    duration = time.monotonic() - t0

    assert max_concurrent == 3
    # If sequential, duration would be >= 0.24s. In parallel, it should finish well under 0.20s.
    assert duration < 0.20
    assert len(env.subagents.calls) == 3


@pytest.mark.asyncio
async def test_dag_dependency_after_enforces_order_and_passes_upstream(env) -> None:
    """B after A waits for A to finish and receives A's summary."""
    env.configure(_config(max_parallel=3))

    call_order: list[str] = []

    class OrderSubagents:
        async def run_inline(self, *, task: str, label: str, **kwargs: Any) -> str:
            agent = label.removeprefix("room:")
            call_order.append(agent)
            if agent == "agent_a":
                await asyncio.sleep(0.05)
                return "Alpha facts summary"
            elif agent == "agent_b":
                # Check that upstream results from agent_a are present in task assignment
                assert "## Upstream results" in task
                assert "@agent_a: Alpha facts summary" in task
                return "Beta copy based on alpha"
            return "ok"

    env.subagents = OrderSubagents()
    env.bind()

    # Delegate B first with after=["agent_a"], then delegate A
    scheduler.record_delegation(
        KEY, "agent_b", "task B", by="owner", runtime=OWNER_RUNTIME, context=CTX, after=("agent_a",)
    )
    scheduler.record_delegation(
        KEY, "agent_a", "task A", by="owner", runtime=OWNER_RUNTIME, context=CTX
    )
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="dag")
    await _drain(KEY)

    assert call_order == ["agent_a", "agent_b"]


@pytest.mark.asyncio
async def test_dag_same_agent_is_strictly_sequential(env) -> None:
    """Two delegations for the same agent never run concurrently."""
    env.configure(_config(max_parallel=3))

    running_for_agent: dict[str, int] = {}
    max_for_same_agent = 0

    class SequentialAgentSubagents:
        async def run_inline(self, *, task: str, label: str, **kwargs: Any) -> str:
            nonlocal max_for_same_agent
            agent = label.removeprefix("room:")
            cnt = running_for_agent.get(agent, 0) + 1
            running_for_agent[agent] = cnt
            max_for_same_agent = max(max_for_same_agent, cnt)
            try:
                await asyncio.sleep(0.05)
                return f"Done {task}"
            finally:
                running_for_agent[agent] -= 1

    env.subagents = SequentialAgentSubagents()
    env.bind()

    scheduler.record_delegation(KEY, "agent_a", "step 1", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.record_delegation(KEY, "agent_a", "step 2", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="dag")
    await _drain(KEY)

    assert max_for_same_agent == 1


@pytest.mark.asyncio
async def test_dag_unresolved_cycle_reports_deadlock_and_stops(env) -> None:
    """Cyclic dependency (A after B, B after A) reports unresolved dependencies."""
    env.configure(_config(max_parallel=2))

    class NoopSubagents:
        async def run_inline(self, **kwargs: Any) -> str:
            return "never called"

    env.subagents = NoopSubagents()
    env.bind()

    scheduler.record_delegation(
        KEY, "agent_a", "task A", by="owner", runtime=OWNER_RUNTIME, context=CTX, after=("agent_b",)
    )
    scheduler.record_delegation(
        KEY, "agent_b", "task B", by="owner", runtime=OWNER_RUNTIME, context=CTX, after=("agent_a",)
    )
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="dag")
    await _drain(KEY)

    outbound = [m.content for m in env.bus.outbound]
    assert any("Dependencies could not be resolved" in m for m in outbound)
    assert any("@agent_a waits for @agent_b" in m for m in outbound)
    assert any("@agent_b waits for @agent_a" in m for m in outbound)


@pytest.mark.asyncio
async def test_dag_chained_turn_budget_pauses_room_under_parallelism(env) -> None:
    """Max chained turns pauses execution even when max_parallel > 1."""
    env.configure(_config(max_parallel=3, max_chained=2))

    calls: list[str] = []

    class BudgetSubagents:
        async def run_inline(self, *, label: str, **kwargs: Any) -> str:
            agent = label.removeprefix("room:")
            calls.append(agent)
            return "done"

    env.subagents = BudgetSubagents()
    env.bind()

    scheduler.record_delegation(KEY, "agent_a", "1", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.record_delegation(KEY, "agent_b", "2", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.record_delegation(KEY, "agent_c", "3", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="dag")
    await _drain(KEY)

    # Only 2 could run before the chained turn budget exhausted
    assert len(calls) == 2
    outbound = [m.content for m in env.bus.outbound]
    assert any("Room paused: chained-turn budget (2) exhausted" in m for m in outbound)


@pytest.mark.asyncio
async def test_dag_one_guest_failure_does_not_cancel_parallel_sibling(env) -> None:
    """If agent_a fails with an exception, parallel agent_b completes and coordinator is summoned."""
    env.configure(_config(max_parallel=2))

    class PartialFailSubagents:
        async def run_inline(self, *, label: str, **kwargs: Any) -> str:
            agent = label.removeprefix("room:")
            if agent == "agent_a":
                raise RuntimeError("database crash")
            await asyncio.sleep(0.04)
            return "agent_b succeeded"

    env.subagents = PartialFailSubagents()
    env.bind()

    scheduler.record_delegation(KEY, "agent_a", "fail", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.record_delegation(KEY, "agent_b", "succeed", by="owner", runtime=OWNER_RUNTIME, context=CTX)
    scheduler.maybe_start_room_run(KEY, channel="telegram", chat_id="dag")
    await _drain(KEY)

    outbound = [m.content for m in env.bus.outbound]
    assert any("Agent A failed: RuntimeError: database crash" in m for m in outbound)
    assert any("Agent B:\nagent_b succeeded" in m for m in outbound)
    # Coordinator summoned with agent_b's success
    assert env.bus.inbound and "agent_b succeeded" in env.bus.inbound[-1].content
