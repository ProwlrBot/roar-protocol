# -*- coding: utf-8 -*-
"""Abstract token use-count store for delegation token enforcement.

The default InMemoryTokenStore is safe for single-worker deployments.
For multi-worker production, use RedisTokenStore (requires redis package).

Both stores are safe against race conditions within their scope:
- InMemoryTokenStore: GIL-safe integer increment (single process)
- RedisTokenStore: INCR is atomic on the Redis server (across processes)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class TokenStore(ABC):
    @abstractmethod
    def get_and_increment(self, token_id: str, max_uses: Optional[int]) -> bool:
        """Atomically increment use count. Returns True if within limit, False if exhausted.

        If max_uses is None (unlimited), always returns True and increments.
        """

    @abstractmethod
    def get_count(self, token_id: str) -> int:
        """Return current use count for a token."""


class InMemoryTokenStore(TokenStore):
    """Single-process in-memory store. NOT safe across multiple workers."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def get_and_increment(self, token_id: str, max_uses: Optional[int]) -> bool:
        current = self._counts.get(token_id, 0)
        if max_uses is not None and current >= max_uses:
            return False
        self._counts[token_id] = current + 1
        return True

    def get_count(self, token_id: str) -> int:
        return self._counts.get(token_id, 0)


class RedisTokenStore(TokenStore):
    """Multi-worker safe token store using Redis INCR.

    Redis INCR is atomic — safe across multiple uvicorn/gunicorn workers.
    Keys are set to expire after 24 hours to prevent unbounded growth.

    Use this in production deployments with more than one worker process.
    The ``redis`` package is imported lazily so the module loads fine without
    it installed — a clear ``ImportError`` is raised only when a method is
    first called.

    Requires: ``pip install roar-sdk[redis]``
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "roar:tok:",
    ) -> None:
        self._redis_url = redis_url
        self._prefix = key_prefix
        self._client = None  # lazy; created on first use

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import redis as _redis
        except ImportError as exc:
            raise ImportError(
                "RedisTokenStore requires the 'redis' package. "
                "Install with: pip install roar-sdk[redis]"
            ) from exc
        self._client = _redis.from_url(
            self._redis_url,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        return self._client

    # Lua script: atomic increment-if-below-limit with TTL.
    # Returns the new count on success, -1 if limit exceeded.
    # This prevents the race where INCR overshoots and permanently
    # blacklists a legitimate token (SEC-001).
    _LUA_INCR_IF_BELOW = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if ARGV[1] == 'unlimited' or current < tonumber(ARGV[1]) then
    local new_count = redis.call('INCR', KEYS[1])
    redis.call('EXPIRE', KEYS[1], 86400)
    return new_count
else
    return -1
end
"""

    def get_and_increment(self, token_id: str, max_uses: Optional[int]) -> bool:
        r = self._get_client()
        key = f"{self._prefix}{token_id}"
        limit = str(max_uses) if max_uses is not None else "unlimited"
        result = r.eval(self._LUA_INCR_IF_BELOW, 1, key, limit)
        return int(result) != -1

    def get_count(self, token_id: str) -> int:
        r = self._get_client()
        val = r.get(f"{self._prefix}{token_id}")
        return int(val) if val else 0
