# -*- coding: utf-8 -*-
"""ROAR Protocol SDK — Server for receiving and dispatching ROAR messages."""

from __future__ import annotations

import inspect
import logging
import os
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union, cast

from .did_resolver import DIDResolutionError, resolve_did_to_public_key
from .streaming import EventBus
from .token_store import InMemoryTokenStore, RedisTokenStore, TokenStore
from .types import (
    AgentCard,
    AgentDirectory,
    AgentIdentity,
    DiscoveryEntry,
    MessageIntent,
    ROARMessage,
    StreamEvent,
)

logger = logging.getLogger(__name__)

HandlerFunc = Callable[
    [ROARMessage], Union[ROARMessage, Coroutine[Any, Any, ROARMessage]]
]


class ROARServer:
    """Receive and dispatch ROAR messages to intent handlers.

    Usage::

        server = ROARServer(
            AgentIdentity(display_name="my-server"),
            port=8089,
            signing_secret="shared-secret",
        )

        @server.on(MessageIntent.DELEGATE)
        async def handle(msg: ROARMessage) -> ROARMessage:
            return ROARMessage(
                **cast(Dict[str, Any], {"from": server.identity, "to": msg.from_identity}),
                intent=MessageIntent.RESPOND,
                payload={"status": "ok"},
                context={"in_reply_to": msg.id},
            )

        # Wire into FastAPI:
        #   response = await server.handle_message(incoming_msg)
        # Or use the built-in serve() method (requires fastapi + uvicorn).
    """

    def __init__(
        self,
        identity: AgentIdentity,
        host: str = "127.0.0.1",
        port: int = 8089,
        *,
        description: str = "",
        skills: Optional[List[str]] = None,
        channels: Optional[List[str]] = None,
        signing_secret: str = "",
        token_store: Optional[TokenStore] = None,
    ) -> None:
        self._identity = identity
        self._host = host
        self._port = port
        self._description = description
        self._skills = skills or []
        self._channels = channels or []
        self._signing_secret = signing_secret
        self._handlers: Dict[MessageIntent, HandlerFunc] = {}
        self._event_bus = EventBus()
        # Server-authoritative token use-count store.
        # The delegate's claimed use_count in the wire payload is ignored;
        # this store is the only source of truth for max_uses enforcement.
        if token_store is not None:
            self._token_store: TokenStore = token_store
        else:
            self._token_store = self._create_default_token_store()

    @staticmethod
    def _create_default_token_store() -> TokenStore:
        """Create token store with Redis fallback to in-memory."""
        redis_url = os.getenv("ROAR_REDIS_URL")
        if redis_url:
            try:
                store = RedisTokenStore(redis_url=redis_url)
                store._get_client().ping()
                logger.info("Using RedisTokenStore at %s", redis_url)
                return store
            except Exception as exc:
                logger.warning(
                    "Redis unavailable (%s), falling back to InMemoryTokenStore", exc
                )
        return InMemoryTokenStore()

    @property
    def identity(self) -> AgentIdentity:
        return self._identity

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def emit(self, event: StreamEvent) -> int:
        """Publish a StreamEvent to all subscribers."""
        return await self._event_bus.publish(event)

    def on(self, intent: MessageIntent) -> Callable[[HandlerFunc], HandlerFunc]:
        """Decorator: register a handler for a specific intent.

        Example::

            @server.on(MessageIntent.DELEGATE)
            async def handle_delegate(msg: ROARMessage) -> ROARMessage:
                ...
        """
        def decorator(handler: HandlerFunc) -> HandlerFunc:
            self._handlers[intent] = handler
            return handler
        return decorator

    async def handle_message(self, msg: ROARMessage, *, _signature_verified: bool = False) -> ROARMessage:
        """Dispatch an incoming message to the registered handler.

        If a ``signing_secret`` was configured, the message's HMAC signature is
        verified before dispatch (unless the caller has already verified it and
        passes ``_signature_verified=True``).

        If the message carries a delegation token in context["delegation_token"],
        it is verified and consumed (use_count incremented). Messages with an
        exhausted or invalid token are rejected before reaching the handler.

        Returns an error response if no handler is registered.
        """
        # SECURITY: verify message signature when a signing secret is configured
        # and the caller has not already performed verification (e.g. serve()).
        if self._signing_secret and not _signature_verified:
            if not msg.verify(self._signing_secret, max_age_seconds=300):
                return ROARMessage(
                    **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                    intent=MessageIntent.RESPOND,
                    payload={"error": "invalid_signature", "message": "Message signature verification failed."},
                    context={"in_reply_to": msg.id},
                )

        # Delegation token enforcement
        raw_token = msg.context.get("delegation_token")
        if raw_token:
            from .delegation import DelegationToken, verify_token
            try:
                token = DelegationToken.model_validate(raw_token)
            except Exception:
                return ROARMessage(
                    **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                    intent=MessageIntent.RESPOND,
                    payload={"error": "invalid_delegation_token", "message": "Malformed delegation token."},
                    context={"in_reply_to": msg.id},
                )

            # SECURITY INVARIANT 1: bind check MUST run before signature verification.
            # Ensures the token was issued to this exact sender — prevents token theft.
            if token.delegate_did != msg.from_identity.did:
                return ROARMessage(
                    **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                    intent=MessageIntent.RESPOND,
                    payload={"error": "delegation_token_unauthorized", "message": "Token was not issued to this agent."},
                    context={"in_reply_to": msg.id},
                )

            # Expiry check (before consuming a use from the store)
            if token.expires_at is not None:
                import time
                if time.time() > token.expires_at:
                    return ROARMessage(
                        **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                        intent=MessageIntent.RESPOND,
                        payload={"error": "delegation_token_exhausted", "message": "Token expired or use limit reached."},
                        context={"in_reply_to": msg.id},
                    )

            # Atomic use-count check + increment via the configured store.
            if not self._token_store.get_and_increment(token.token_id, token.max_uses):
                return ROARMessage(
                    **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                    intent=MessageIntent.RESPOND,
                    payload={"error": "delegation_token_exhausted", "message": "Token expired or use limit reached."},
                    context={"in_reply_to": msg.id},
                )

            # Determine the delegator's public key for signature verification.
            # SECURITY INVARIANT 2: NEVER use msg.from_identity.public_key —
            # that field is attacker-controlled. Always resolve from a trusted source.
            # SECURITY INVARIANT 3: fail closed on resolution failure.
            try:
                delegator_public_key = resolve_did_to_public_key(token.delegator_did)
            except DIDResolutionError as exc:
                logger.warning(
                    "DID resolution failed for delegator '%s': %s",
                    token.delegator_did,
                    exc,
                )
                return ROARMessage(
                    **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                    intent=MessageIntent.RESPOND,
                    payload={
                        "error": "delegation_unverifiable",
                        "message": "Could not resolve delegator DID.",
                    },
                    context={"in_reply_to": msg.id},
                )

            try:
                if not verify_token(token, delegator_public_key):
                    return ROARMessage(
                        **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                        intent=MessageIntent.RESPOND,
                        payload={
                            "error": "invalid_delegation_signature",
                            "message": "Delegation token signature verification failed.",
                        },
                        context={"in_reply_to": msg.id},
                    )
            except ImportError:
                logger.error(
                    "cryptography package not installed — cannot verify Ed25519 delegation token. "
                    "Install with: pip install roar-sdk[ed25519]"
                )
                return ROARMessage(
                    **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                    intent=MessageIntent.RESPOND,
                    payload={
                        "error": "delegation_unverifiable",
                        "message": "Server cannot verify Ed25519 signatures (missing cryptography package).",
                    },
                    context={"in_reply_to": msg.id},
                )

        handler = self._handlers.get(msg.intent)
        if handler is None:
            logger.warning("No handler for intent '%s' from %s", msg.intent, msg.from_identity.did)
            return ROARMessage(
                **cast(Dict[str, Any], {"from": self._identity, "to": msg.from_identity}),
                intent=MessageIntent.RESPOND,
                payload={
                    "error": "unhandled_intent",
                    "message": f"No handler registered for intent '{msg.intent}'",
                },
                context={"in_reply_to": msg.id},
            )

        if inspect.iscoroutinefunction(handler):
            return await handler(msg)
        return handler(msg)  # type: ignore[return-value]

    def get_card(self) -> AgentCard:
        """Return an AgentCard describing this server."""
        return AgentCard(
            identity=self._identity,
            description=self._description,
            skills=self._skills,
            channels=self._channels,
            endpoints={"http": f"http://{self._host}:{self._port}"},
        )

    def register_with_directory(self, directory: AgentDirectory) -> DiscoveryEntry:
        return directory.register(self.get_card())

    def serve(self) -> None:
        """Start an HTTP server using FastAPI + uvicorn.

        Requires: pip install 'roar-sdk[server]'

        Exposes:
          POST /roar/message  — receive ROARMessage, return response
          GET  /roar/agents   — list this server's AgentCard
        """
        try:
            from fastapi import FastAPI, Request
            from fastapi.responses import JSONResponse
            import uvicorn
        except ImportError:
            raise ImportError(
                "Server mode requires fastapi and uvicorn. "
                "Install them: pip install 'roar-sdk[server]'"
            )

        app = FastAPI(title=f"ROAR Agent: {self._identity.display_name}")
        # Expose Request in module globals so FastAPI can resolve the type
        # annotation despite `from __future__ import annotations`.
        globals()["Request"] = Request
        server_ref = self

        # Prometheus metrics (optional — requires monitoring extra)
        try:
            from prometheus_fastapi_instrumentator import Instrumentator
            Instrumentator().instrument(app).expose(app, endpoint="/metrics")
        except ImportError:
            pass

        # Replay-protection guard (bounded; see dedup.py for eviction details).
        from .dedup import IdempotencyGuard as _IdempotencyGuard
        _serve_dedup = _IdempotencyGuard(max_keys=10_000, ttl_seconds=600.0)

        # StrictMessageVerifier for production message validation
        from .verifier import StrictMessageVerifier as _StrictVerifier
        _strict_verifier: _StrictVerifier | None = None
        if server_ref._signing_secret:
            _strict_verifier = _StrictVerifier(
                hmac_secret=server_ref._signing_secret,
                replay_guard=_serve_dedup,
            )

        @app.post("/roar/message")
        async def receive_message(request: Request):
            MAX_BODY_BYTES = 1_048_576  # 1 MiB
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > MAX_BODY_BYTES:
                        return JSONResponse(
                            {"error": "request_too_large", "message": "Request body exceeds 1 MiB limit"},
                            status_code=413,
                        )
                except ValueError:
                    pass  # malformed content-length — let read proceed and re-check below

            raw_body = await request.body()
            if len(raw_body) > MAX_BODY_BYTES:
                return JSONResponse(
                    {"error": "request_too_large", "message": "Request body exceeds 1 MiB limit"},
                    status_code=413,
                )

            import json as _json
            try:
                body = _json.loads(raw_body)
                msg = ROARMessage.model_validate(body)
            except Exception:
                # Do not surface parse/validation details — they may expose schema info
                return JSONResponse(
                    {"error": "invalid_message", "message": "Request body is not a valid ROAR message."},
                    status_code=400,
                )

            # Strict verification (covers signature, replay, timestamps)
            if _strict_verifier is not None:
                vr = _strict_verifier.verify(msg)
                if not vr.ok:
                    status = 401 if "signature" in vr.error else 400
                    return JSONResponse(
                        {"error": "verification_failed", "message": vr.error},
                        status_code=status,
                    )
            else:
                # Fallback: basic signing secret check
                if server_ref._signing_secret:
                    if not msg.verify(server_ref._signing_secret, max_age_seconds=300):
                        return JSONResponse(
                            {"error": "invalid_signature", "message": "HMAC verification failed"},
                            status_code=401,
                        )
                # Replay protection
                if _serve_dedup.is_duplicate(msg.id):
                    return JSONResponse(
                        {"error": "duplicate_message", "message": "Message already processed."},
                        status_code=409,
                    )

            response = await server_ref.handle_message(msg, _signature_verified=True)
            return response.model_dump(by_alias=True)

        @app.get("/roar/agents")
        async def list_agents():
            return {"agents": [server_ref.get_card().model_dump()]}

        if not server_ref._signing_secret:
            logger.warning(
                "ROAR server '%s' starting WITHOUT signing_secret — "
                "ALL messages will be accepted without authentication. "
                "Set signing_secret to enable HMAC verification.",
                self._identity.display_name,
            )

        logger.info(
            "ROAR server '%s' starting on http://%s:%d",
            self._identity.display_name,
            self._host,
            self._port,
        )
        uvicorn.run(app, host=self._host, port=self._port, log_level="warning")
