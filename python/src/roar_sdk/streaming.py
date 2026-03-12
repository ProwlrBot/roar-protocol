# -*- coding: utf-8 -*-
"""ROAR Protocol SDK — In-process event bus for Layer 5 streaming.

Zero external dependencies. Each subscriber gets a bounded asyncio queue.
Backpressure: when a queue is full, the oldest event is dropped.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import AsyncIterator, Deque, Dict, List, Optional

from .types import StreamEvent

logger = logging.getLogger(__name__)


@dataclass
class StreamFilter:
    """Filter for selecting which events a subscriber receives.

    All non-empty filters are AND-combined.
    """

    event_types: List[str] = field(default_factory=list)
    source_dids: List[str] = field(default_factory=list)
    session_ids: List[str] = field(default_factory=list)

    def matches(self, event: StreamEvent) -> bool:
        if self.event_types and event.type not in self.event_types:
            return False
        if self.source_dids and event.source not in self.source_dids:
            return False
        if self.session_ids and event.session_id not in self.session_ids:
            return False
        return True


class Subscription:
    """An active event subscription. Async-iterable."""

    def __init__(
        self,
        sub_id: str,
        filter_spec: StreamFilter,
        queue: asyncio.Queue,
        bus: "EventBus",
    ) -> None:
        self.id = sub_id
        self.filter = filter_spec
        self._queue = queue
        self._bus = bus
        self._closed = False
        self.events_received: int = 0
        self.events_dropped: int = 0

    @property
    def closed(self) -> bool:
        return self._closed

    async def __aiter__(self) -> AsyncIterator[StreamEvent]:
        while not self._closed:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                self.events_received += 1
                yield event
            except asyncio.TimeoutError:
                continue

    async def get(self, timeout: float = 5.0) -> Optional[StreamEvent]:
        """Get the next event, or None on timeout."""
        if self._closed:
            return None
        try:
            event = await asyncio.wait_for(self._queue.get(), timeout=timeout)
            self.events_received += 1
            return event
        except asyncio.TimeoutError:
            return None

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._bus._unsubscribe(self.id)


class EventBus:
    """In-process pub/sub event bus for ROAR streaming.

    Usage::

        bus = EventBus()
        sub = bus.subscribe(StreamFilter(event_types=["tool_call"]))
        await bus.publish(StreamEvent(type="tool_call", data={...}))
        event = await sub.get(timeout=2.0)
    """

    def __init__(self, max_buffer: int = 1000, replay_size: int = 100) -> None:
        self._max_buffer = max_buffer
        self._replay_buffer: Deque[StreamEvent] = deque(maxlen=replay_size)
        self._subscriptions: Dict[str, Subscription] = {}
        self._event_count: int = 0

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    @property
    def event_count(self) -> int:
        return self._event_count

    def subscribe(
        self,
        filter_spec: Optional[StreamFilter] = None,
        buffer_size: Optional[int] = None,
        replay: bool = False,
    ) -> Subscription:
        """Create a new subscription.

        Args:
            filter_spec: Event filter (None = receive all events).
            buffer_size: Per-subscriber buffer size.
            replay: Pre-fill with recent events from the replay buffer.
        """
        sub_id = f"sub-{uuid.uuid4().hex[:12]}"
        queue: asyncio.Queue = asyncio.Queue(maxsize=buffer_size or self._max_buffer)
        effective_filter = filter_spec or StreamFilter()

        if replay:
            for event in self._replay_buffer:
                if effective_filter.matches(event):
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        break

        sub = Subscription(sub_id=sub_id, filter_spec=effective_filter, queue=queue, bus=self)
        self._subscriptions[sub_id] = sub
        return sub

    async def publish(self, event: StreamEvent) -> int:
        """Publish an event to all matching subscribers. Returns delivery count."""
        self._event_count += 1
        self._replay_buffer.append(event)
        delivered = 0

        for sub in list(self._subscriptions.values()):
            if sub.closed or not sub.filter.matches(event):
                continue
            try:
                sub._queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                try:
                    sub._queue.get_nowait()
                    sub.events_dropped += 1
                except asyncio.QueueEmpty:
                    pass
                try:
                    sub._queue.put_nowait(event)
                    delivered += 1
                except asyncio.QueueFull:
                    sub.events_dropped += 1
                    logger.warning("Subscription %s dropping events (buffer full)", sub.id)

        return delivered

    def _unsubscribe(self, sub_id: str) -> None:
        self._subscriptions.pop(sub_id, None)

    def close_all(self) -> None:
        for sub in list(self._subscriptions.values()):
            sub._closed = True
        self._subscriptions.clear()
