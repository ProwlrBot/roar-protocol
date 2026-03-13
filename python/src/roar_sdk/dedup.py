# -*- coding: utf-8 -*-
"""Idempotency guard — deduplicates events or messages by key.

Uses a bounded LRU-style ordered dict of seen keys to ensure at-least-once
delivery doesn't result in duplicate processing. Keys expire after a
configurable TTL.

Usage::

    guard = IdempotencyGuard(max_keys=10_000, ttl_seconds=300.0)

    if guard.is_duplicate(message.id):
        return  # already processed

    process(message)
"""

from __future__ import annotations

import time
from collections import OrderedDict


class IdempotencyGuard:
    """Deduplicates events using idempotency keys.

    Each event should carry a unique key (typically the message/event ID).
    The guard tracks seen keys and rejects duplicates within the TTL window.

    Attributes:
        max_keys: Maximum number of keys to track (LRU eviction beyond this).
        ttl_seconds: How long to remember a key before allowing reuse.
    """

    def __init__(self, max_keys: int = 10_000, ttl_seconds: float = 300.0) -> None:
        self._max_keys = max_keys
        self._ttl = ttl_seconds
        self._seen: OrderedDict[str, float] = OrderedDict()

    def is_duplicate(self, key: str) -> bool:
        """Check if this key was seen recently.

        Args:
            key: Idempotency key (e.g., message ID or content hash).

        Returns:
            True if the key was seen within the TTL window (it's a duplicate).
            False if this is the first time the key is seen (records it).
        """
        self._evict_expired()
        now = time.time()

        if key in self._seen:
            ts = self._seen[key]
            if now - ts < self._ttl:
                return True
            del self._seen[key]

        self._seen[key] = now

        # LRU eviction if over capacity
        while len(self._seen) > self._max_keys:
            self._seen.popitem(last=False)

        return False

    def mark_seen(self, key: str) -> None:
        """Explicitly mark a key as seen without checking."""
        self._seen[key] = time.time()
        while len(self._seen) > self._max_keys:
            self._seen.popitem(last=False)

    @property
    def size(self) -> int:
        """Number of currently tracked keys."""
        return len(self._seen)

    def clear(self) -> None:
        """Clear all tracked keys."""
        self._seen.clear()

    def _evict_expired(self) -> None:
        """Remove keys older than TTL. OrderedDict is insertion-ordered,
        so expired keys are at the front."""
        if not self._seen:
            return
        cutoff = time.time() - self._ttl
        while self._seen:
            key, ts = next(iter(self._seen.items()))
            if ts > cutoff:
                break
            del self._seen[key]
