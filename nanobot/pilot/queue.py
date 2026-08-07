"""Prioritized bounded capture queue with lower-priority eviction."""

from __future__ import annotations

import asyncio
import heapq
from dataclasses import dataclass, field

from nanobot.pilot.types import QueueEvent


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    """Content-free snapshot of queue state."""

    capacity: int
    depth: int
    dropped_by_kind: dict[str, int]
    accepted_total: int


@dataclass(order=True)
class _PrioritizedItem:
    priority: int
    sequence: int
    event: QueueEvent = field(compare=False)


class CaptureQueue:
    """Bounded, prioritized queue for capture events.

    Events with lower numerical priority value take precedence.
    When full, enqueuing a higher-priority event will evict the oldest lowest-priority item.
    """

    def __init__(self, capacity: int = 1000) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be greater than 0")
        self.capacity = capacity
        self._heap: list[_PrioritizedItem] = []
        self._sequence = 0
        self._accepted_total = 0
        self._dropped_by_kind: dict[str, int] = {}
        self._closed = False
        self._cond = asyncio.Condition()

    async def put(self, event: QueueEvent) -> bool:
        """Enqueue an event. Evicts lowest priority item if full and event has higher priority."""
        async with self._cond:
            if self._closed:
                return False

            if len(self._heap) >= self.capacity:
                # Find the lowest priority (highest numerical priority value) item in heap
                worst_item = max(self._heap, key=lambda item: (item.priority, -item.sequence))
                if event.priority.value < worst_item.priority:
                    # Evict worst item
                    self._heap.remove(worst_item)
                    heapq.heapify(self._heap)
                    self._dropped_by_kind[worst_item.event.kind] = (
                        self._dropped_by_kind.get(worst_item.event.kind, 0) + 1
                    )
                else:
                    # Drop incoming event
                    self._dropped_by_kind[event.kind] = (
                        self._dropped_by_kind.get(event.kind, 0) + 1
                    )
                    return False

            self._sequence += 1
            item = _PrioritizedItem(
                priority=event.priority.value,
                sequence=self._sequence,
                event=event,
            )
            heapq.heappush(self._heap, item)
            self._accepted_total += 1
            self._cond.notify_all()
            return True

    async def get(self) -> QueueEvent | None:
        """Pop the highest priority (lowest priority number, oldest sequence) event."""
        async with self._cond:
            while not self._heap and not self._closed:
                await self._cond.wait()

            if not self._heap:
                return None

            item = heapq.heappop(self._heap)
            return item.event

    async def get_batch(self, max_items: int = 100) -> list[QueueEvent]:
        """Pop up to max_items events in priority order."""
        async with self._cond:
            while not self._heap and not self._closed:
                await self._cond.wait()

            batch: list[QueueEvent] = []
            while self._heap and len(batch) < max_items:
                item = heapq.heappop(self._heap)
                batch.append(item.event)
            return batch

    async def snapshot(self) -> QueueSnapshot:
        """Return content-free state snapshot."""
        async with self._cond:
            return QueueSnapshot(
                capacity=self.capacity,
                depth=len(self._heap),
                dropped_by_kind=dict(self._dropped_by_kind),
                accepted_total=self._accepted_total,
            )

    async def close(self) -> None:
        """Close the queue and notify all waiting consumers."""
        async with self._cond:
            self._closed = True
            self._cond.notify_all()
