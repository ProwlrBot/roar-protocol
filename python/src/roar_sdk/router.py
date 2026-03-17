# -*- coding: utf-8 -*-
"""FastAPI router for receiving ROAR messages.

Mount on a FastAPI app to accept ROAR messages over HTTP, WebSocket,
and SSE. Includes token-bucket rate limiting (no external deps) and
replay protection.

Usage::

    from fastapi import FastAPI
    from roar_sdk import ROARServer, AgentIdentity
    from roar_sdk.router import create_roar_router

    identity = AgentIdentity(display_name="my-agent")
    server = ROARServer(identity)

    app = FastAPI()
    app.include_router(create_roar_router(server, rate_limit=60))

Requires: pip install 'roar-sdk[server]'
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from .types import ROARMessage
from .verifier import StrictMessageVerifier

logger = logging.getLogger(__name__)

_MAX_SSE_CONNECTIONS = 100


class TokenBucket:
    """In-memory token bucket rate limiter.

    Tokens refill at a steady rate. Each request consumes one token.
    When empty, requests are rejected until tokens refill.

    Args:
        max_tokens: Maximum tokens (burst capacity).
        refill_rate: Tokens added per second.
    """

    def __init__(self, max_tokens: float, refill_rate: float) -> None:
        self._max = max_tokens
        self._rate = refill_rate
        self._tokens = max_tokens
        self._last = time.monotonic()

    def consume(self) -> bool:
        """Try to consume one token. Returns True if successful."""
        now = time.monotonic()
        self._tokens = min(self._max, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


def _safe_error(exc: Exception) -> str:
    """Return a sanitized error message without internal details."""
    if "validation" in type(exc).__name__.lower():
        return "Message validation failed. Check the request body format."
    return "Internal processing error."


def create_roar_router(
    server: Any,
    rate_limit: int = 0,
    auth_token: str = "",
    strict_verifier: Optional[StrictMessageVerifier] = None,
    auth_config: Optional[Any] = None,
) -> APIRouter:
    """Create a FastAPI router wired to a ROARServer.

    Args:
        server: A ROARServer instance.
        rate_limit: Max requests per minute (0 = disabled). Uses token bucket.
        auth_token: Optional Bearer token for WebSocket/SSE auth.
        auth_config: Optional AuthConfig for pluggable auth middleware.
            If provided, all routes except /health are protected.

    Returns:
        APIRouter with POST /roar/message, WS /roar/ws, GET /roar/events,
        and GET /roar/health endpoints.
    """
    import hmac as _hmac

    from .server import ROARServer

    if not isinstance(server, ROARServer):
        raise TypeError(f"create_roar_router: 'server' must be a ROARServer, got {type(server).__name__}")

    # Build route-level dependencies from auth_config
    _route_deps: list = []
    if auth_config is not None:
        from .auth_middleware import require_auth
        _route_deps.append(Depends(require_auth(auth_config)))

    router = APIRouter(prefix="/roar", tags=["roar"])

    _limiter: Optional[TokenBucket] = None
    if rate_limit > 0:
        _limiter = TokenBucket(max_tokens=float(rate_limit), refill_rate=rate_limit / 60.0)

    _active_sse: Set[str] = set()

    # Replay protection: bounded dict of message_id → seen_at
    _seen: Dict[str, float] = {}
    _SEEN_MAX = 10_000
    _SEEN_TTL = 600.0

    def _check_rate() -> Optional[JSONResponse]:
        if _limiter is not None and not _limiter.consume():
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limited", "detail": "Too many requests."},
            )
        return None

    def _check_replay(msg_id: str) -> bool:
        now = time.time()
        if len(_seen) > _SEEN_MAX:
            expired = [k for k, v in _seen.items() if now - v > _SEEN_TTL]
            for k in expired:
                _seen.pop(k, None)
        if msg_id in _seen:
            return True
        _seen[msg_id] = now
        return False

    def _verify_bearer(authorization: Optional[str]) -> None:
        if not auth_token:
            return
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization")
        if not _hmac.compare_digest(authorization[7:], auth_token):
            raise HTTPException(status_code=401, detail="Invalid authorization token")

    @router.post("/message", dependencies=_route_deps)
    async def handle_message(body: Dict[str, Any], request: Request) -> Any:
        """Receive a ROAR message via HTTP POST."""
        limited = _check_rate()
        if limited is not None:
            return limited

        try:
            incoming = ROARMessage.model_validate(body)
        except Exception as exc:
            logger.warning("Invalid ROAR message: %s", exc)
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_message", "detail": _safe_error(exc)},
            )

        # Strict verification (if enabled) — covers signature, replay, timestamps
        if strict_verifier is not None:
            result = strict_verifier.verify(incoming)
            if not result.ok:
                logger.warning("StrictMessageVerifier rejected message %s: %s", incoming.id, result.error)
                return JSONResponse(
                    status_code=400,
                    content={"error": "verification_failed", "detail": result.error},
                )
        else:
            # Fallback to basic signing secret check
            if server._signing_secret and not incoming.verify(server._signing_secret):
                logger.warning("Signature verification failed for message %s", incoming.id)
                return JSONResponse(
                    status_code=403,
                    content={"error": "signature_invalid", "detail": "HMAC signature verification failed."},
                )

            if _check_replay(incoming.id):
                return JSONResponse(
                    status_code=409,
                    content={"error": "duplicate_message", "detail": "Message already processed."},
                )

        response = await server.handle_message(incoming)
        return response.model_dump(by_alias=True)

    @router.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        """Bidirectional WebSocket endpoint for ROAR messages.

        If auth_token is configured, the first frame must be:
        ``{"type": "auth", "token": "<bearer-token>"}``
        """
        await ws.accept()

        if auth_token:
            try:
                auth_data = json.loads(await ws.receive_text())
                if auth_data.get("type") != "auth" or not _hmac.compare_digest(
                    auth_data.get("token", ""), auth_token
                ):
                    await ws.send_text(json.dumps({"error": "auth_failed"}))
                    await ws.close(code=4001)
                    return
                await ws.send_text(json.dumps({"type": "auth_ok"}))
            except Exception:
                await ws.close(code=4001)
                return

        logger.info("ROAR WebSocket connection established")
        try:
            while True:
                raw = await ws.receive_text()

                if _limiter is not None and not _limiter.consume():
                    await ws.send_text(json.dumps({"error": "rate_limited"}))
                    continue

                try:
                    incoming = ROARMessage.model_validate(json.loads(raw))

                    if server._signing_secret and not incoming.verify(server._signing_secret):
                        await ws.send_text(json.dumps({"error": "signature_invalid"}))
                        continue

                    if _check_replay(incoming.id):
                        await ws.send_text(json.dumps({"error": "duplicate_message"}))
                        continue

                    response = await server.handle_message(incoming)
                    await ws.send_text(json.dumps(response.model_dump(by_alias=True)))
                except Exception as exc:
                    await ws.send_text(json.dumps({"error": "processing_error", "detail": _safe_error(exc)}))
        except WebSocketDisconnect:
            logger.info("ROAR WebSocket disconnected")

    @router.get("/events", dependencies=_route_deps)
    async def event_stream(
        request: Request,
        session_id: str = "",
        event_type: str = "",
        source: str = "",
        authorization: Optional[str] = Header(None),
    ) -> Any:
        """SSE endpoint for streaming ROAR events."""
        _verify_bearer(authorization)
        limited = _check_rate()
        if limited is not None:
            return limited

        if len(_active_sse) >= _MAX_SSE_CONNECTIONS:
            return JSONResponse(
                status_code=503,
                content={"error": "too_many_connections", "detail": "SSE connection limit reached."},
            )

        import uuid as _uuid

        conn_id = _uuid.uuid4().hex[:12]

        from .streaming import StreamFilter

        filter_spec = StreamFilter(
            event_types=[t.strip() for t in event_type.split(",") if t.strip()],
            source_dids=[source] if source else [],
            session_ids=[session_id] if session_id else [],
        )

        async def generate():
            _active_sse.add(conn_id)
            try:
                yield 'event: connected\ndata: {"status": "streaming"}\n\n'
                sub = server.event_bus.subscribe(filter_spec)
                try:
                    async for event in sub:
                        data = json.dumps({
                            "type": event.type,
                            "source": event.source,
                            "session_id": event.session_id,
                            "data": event.data,
                            "timestamp": event.timestamp,
                        })
                        yield f"event: {event.type}\ndata: {data}\n\n"
                finally:
                    sub.close()
            finally:
                _active_sse.discard(conn_id)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-ROAR-Protocol": "1.0",
            },
        )

    @router.get("/health")
    async def health() -> Dict[str, Any]:
        """Health check — minimal info, no auth required."""
        return {"status": "ok", "protocol": "roar/1.0"}

    return router
