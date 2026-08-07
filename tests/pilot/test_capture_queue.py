"""Tests for CaptureQueue."""

import asyncio

import pytest

from nanobot.pilot.queue import CaptureQueue
from nanobot.pilot.types import CapturePriority, QueueEvent


def make_event(event_id: str, priority: CapturePriority, kind: str = "test") -> QueueEvent:
    return QueueEvent(
        event_id=event_id,
        priority=priority,
        kind=kind,
        payload={"id": event_id},
        created_at_ms=1000,
    )


@pytest.mark.asyncio
async def test_priority_ordering() -> None:
    q = CaptureQueue(capacity=10)
    await q.put(make_event("e_artifact", CapturePriority.ARTIFACT))
    await q.put(make_event("e_consent", CapturePriority.CONSENT))
    await q.put(make_event("e_feedback", CapturePriority.FEEDBACK))

    item1 = await q.get()
    item2 = await q.get()
    item3 = await q.get()

    assert item1 is not None and item1.event_id == "e_consent"
    assert item2 is not None and item2.event_id == "e_feedback"
    assert item3 is not None and item3.event_id == "e_artifact"


@pytest.mark.asyncio
async def test_eviction_when_full() -> None:
    q = CaptureQueue(capacity=2)
    await q.put(make_event("a1", CapturePriority.ARTIFACT, kind="artifact"))
    await q.put(make_event("a2", CapturePriority.ATTEMPT, kind="attempt"))

    # Enqueue higher priority event (FEEDBACK)
    success = await q.put(make_event("f1", CapturePriority.FEEDBACK, kind="feedback"))
    assert success is True

    snap = await q.snapshot()
    assert snap.depth == 2
    assert snap.dropped_by_kind.get("artifact") == 1

    e1 = await q.get()
    e2 = await q.get()
    assert e1 is not None and e1.event_id == "f1"
    assert e2 is not None and e2.event_id == "a2"


@pytest.mark.asyncio
async def test_drop_lower_priority_when_full() -> None:
    q = CaptureQueue(capacity=2)
    await q.put(make_event("c1", CapturePriority.CONSENT, kind="consent"))
    await q.put(make_event("f1", CapturePriority.FEEDBACK, kind="feedback"))

    # Enqueue lower priority event (ARTIFACT)
    success = await q.put(make_event("a1", CapturePriority.ARTIFACT, kind="artifact"))
    assert success is False

    snap = await q.snapshot()
    assert snap.dropped_by_kind.get("artifact") == 1


@pytest.mark.asyncio
async def test_async_get_batch_and_close() -> None:
    q = CaptureQueue(capacity=10)

    async def worker() -> list[QueueEvent]:
        return await q.get_batch(max_items=5)

    task = asyncio.create_task(worker())
    await asyncio.sleep(0.01)
    await q.put(make_event("e1", CapturePriority.FINAL))
    await q.put(make_event("e2", CapturePriority.FINAL))

    res = await task
    assert len(res) == 2
    assert res[0].event_id == "e1"

    await q.close()
    empty = await q.get()
    assert empty is None
