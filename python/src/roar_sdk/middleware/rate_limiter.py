# -*- coding: utf-8 -*-
"""Redis-backed per-IP rate limiting middleware for FastAPI/Starlette.

Provides two sliding windows (per-minute and per-hour) using atomic
Redis INCR+EXPIRE pipelines. Gracefully degrades if Redis is unavailable
(requests pass through rather than being blocked).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class RedisRateLimiter(BaseHTTPMiddleware):
    """Per-IP rate limiter backed by Redis.

    Configuration via environment variables:
        ROAR_RATE_LIMIT_PER_MINUTE  (default: 100)
        ROAR_RATE_LIMIT_PER_HOUR    (default: 1000)
        ROAR_REDIS_URL              (default: redis://localhost:6379)
    """

    def __init__(
        self,
        app,
        redis_url: Optional[str] = None,
        per_minute: Optional[int] = None,
        per_hour: Optional[int] = None,
    ) -> None:
        super().__init__(app)
        self._redis_url = redis_url or os.getenv(
            "ROAR_REDIS_URL", "redis://localhost:6379"
        )
        self._per_minute = per_minute or int(
            os.getenv("ROAR_RATE_LIMIT_PER_MINUTE", "100")
        )
        self._per_hour = per_hour or int(
            os.getenv("ROAR_RATE_LIMIT_PER_HOUR", "1000")
        )
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import redis

            self._client = redis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
            self._client.ping()
            return self._client
        except Exception as exc:
            logger.warning("Redis unavailable for rate limiting: %s", exc)
            self._client = None
            return None

    # RFC 1918 + loopback networks for trusted proxy detection (SEC-010 fix)
    _TRUSTED_NETS = None

    @classmethod
    def _get_trusted_nets(cls):
        if cls._TRUSTED_NETS is None:
            import ipaddress
            cls._TRUSTED_NETS = [
                ipaddress.ip_network("127.0.0.0/8"),
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918, NOT 172.0.0.0/8
                ipaddress.ip_network("192.168.0.0/16"),
                ipaddress.ip_network("::1/128"),
                ipaddress.ip_network("fc00::/7"),
            ]
        return cls._TRUSTED_NETS

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, only trusting X-Forwarded-For from RFC 1918 proxies."""
        import ipaddress
        client_ip = request.client.host if request.client else "unknown"
        try:
            addr = ipaddress.ip_address(client_ip)
            if any(addr in net for net in self._get_trusted_nets()):
                forwarded = request.headers.get("x-forwarded-for")
                if forwarded:
                    return forwarded.split(",")[0].strip()
        except ValueError:
            pass
        return client_ip

    def _check_limit(self, r, key: str, limit: int, window: int) -> tuple[int, bool]:
        """Atomic rate limit check. Returns (current_count, within_limit)."""
        pipe = r.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, window)
        result = pipe.execute()
        count = result[0]
        return count, count <= limit

    async def dispatch(self, request: Request, call_next) -> Response:
        r = self._get_client()
        if r is None:
            # Redis unavailable — pass through
            return await call_next(request)

        ip = self._get_client_ip(request)
        now_minute = int(time.time() // 60)
        now_hour = int(time.time() // 3600)

        try:
            minute_key = f"roar:rl:{ip}:{now_minute}:m"
            hour_key = f"roar:rl:{ip}:{now_hour}:h"

            minute_count, minute_ok = self._check_limit(
                r, minute_key, self._per_minute, 60
            )
            hour_count, hour_ok = self._check_limit(
                r, hour_key, self._per_hour, 3600
            )

            if not minute_ok:
                remaining_seconds = 60 - (int(time.time()) % 60)
                return JSONResponse(
                    {
                        "error": "rate_limited",
                        "message": f"Rate limit exceeded ({self._per_minute}/min). Retry after {remaining_seconds}s.",
                    },
                    status_code=429,
                    headers={"Retry-After": str(remaining_seconds)},
                )

            if not hour_ok:
                remaining_seconds = 3600 - (int(time.time()) % 3600)
                return JSONResponse(
                    {
                        "error": "rate_limited",
                        "message": f"Rate limit exceeded ({self._per_hour}/hour). Retry after {remaining_seconds}s.",
                    },
                    status_code=429,
                    headers={"Retry-After": str(remaining_seconds)},
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit-Minute"] = str(self._per_minute)
            response.headers["X-RateLimit-Remaining-Minute"] = str(
                max(0, self._per_minute - minute_count)
            )
            response.headers["X-RateLimit-Limit-Hour"] = str(self._per_hour)
            response.headers["X-RateLimit-Remaining-Hour"] = str(
                max(0, self._per_hour - hour_count)
            )
            return response

        except Exception as exc:
            logger.warning("Rate limiter error, passing through: %s", exc)
            return await call_next(request)
