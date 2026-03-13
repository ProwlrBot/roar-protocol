# -*- coding: utf-8 -*-
"""TTL + LRU discovery cache for agent lookup results.

Wraps any agent directory with a fast in-memory cache layer.
Entries are evicted when they expire (TTL) or when the cache is
at capacity (LRU eviction of the oldest entry).

Usage::

    cache = DiscoveryCache(max_entries=500, default_ttl=300.0)

    # On lookup
    entry = cache.get(did)
    if entry is None:
        entry = directory.lookup(did)
        if entry:
            cache.put(entry)
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional

from .types import DiscoveryEntry


@dataclass
class _CacheEntry:
    entry: DiscoveryEntry
    cached_at: float
    ttl: float

    @property
    def expired(self) -> bool:
        return time.time() - self.cached_at > self.ttl


class DiscoveryCache:
    """TTL + LRU discovery cache.

    Args:
        max_entries: Maximum number of entries before LRU eviction.
        default_ttl: Default time-to-live in seconds.
    """

    def __init__(self, max_entries: int = 1000, default_ttl: float = 300.0) -> None:
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        self._cache: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, did: str) -> Optional[DiscoveryEntry]:
        """Look up a cached entry by DID. Returns None on miss or expiry."""
        ce = self._cache.get(did)
        if ce is None:
            self._misses += 1
            return None
        if ce.expired:
            del self._cache[did]
            self._misses += 1
            return None
        self._cache.move_to_end(did)
        self._hits += 1
        return ce.entry

    def put(self, entry: DiscoveryEntry, ttl: Optional[float] = None) -> None:
        """Cache a discovery entry.

        Args:
            entry: The discovery entry to cache.
            ttl: Override TTL in seconds (uses default_ttl if omitted).
        """
        did = entry.agent_card.identity.did
        self._cache[did] = _CacheEntry(
            entry=entry,
            cached_at=time.time(),
            ttl=ttl if ttl is not None else self._default_ttl,
        )
        self._cache.move_to_end(did)
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)

    def invalidate(self, did: str) -> bool:
        """Remove a specific entry from the cache."""
        if did in self._cache:
            del self._cache[did]
            return True
        return False

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    def search(self, capability: str) -> List[DiscoveryEntry]:
        """Search cached entries by capability string."""
        self._evict_expired()
        return [
            ce.entry
            for ce in self._cache.values()
            if capability in ce.entry.agent_card.identity.capabilities
               or capability in ce.entry.agent_card.skills
        ]

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def stats(self) -> Dict:
        total = self._hits + self._misses
        return {
            "size": self.size,
            "max_entries": self._max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }

    def _evict_expired(self) -> None:
        expired = [did for did, ce in self._cache.items() if ce.expired]
        for did in expired:
            del self._cache[did]
