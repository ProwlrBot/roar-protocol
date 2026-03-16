# -*- coding: utf-8 -*-
"""ROAR Protocol SDK — Server for receiving and dispatching ROAR messages."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from .streaming import EventBus
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
                **{"from": server.identity, "to": msg.from_identity},
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
        # Server-authoritative use counts keyed by token_id.
        # The delegate's claimed use_count in the wire payload is ignored;
        # this dict is the only source of truth for max_uses enforcement.
        # NOTE: _token_use_counts is in-process memory. Multi-worker deployments
        # (e.g. uvicorn --workers N) will have per-worker counters, meaning a
        # max_uses=1 token can be consumed up to N times. For multi-worker
        # production deployments, replace this dict with a shared atomic store
        # (Redis INCR, database row with SELECT FOR UPDATE, etc.).
        self._token_use_counts: Dict[str, int] = {}

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

    async def handle_message(self, msg: ROARMessage) -> ROARMessage:
        """Dispatch an incoming message to the registered handler.

        If the message carries a delegation token in context["delegation_token"],
        it is verified and consumed (use_count incremented). Messages with an
        exhausted or invalid token are rejected before reaching the handler.

        Returns an error response if no handler is registered.
        """
        # Delegation token enforcement
        raw_token = msg.context.get("delegation_token")
        if raw_token:
            from .delegation import DelegationToken, verify_token
            try:
                token = DelegationToken.model_validate(raw_token)
            except Exception:
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"error": "invalid_delegation_token", "message": "Malformed delegation token."},
                    context={"in_reply_to": msg.id},
                )
            # Replace the delegate-supplied use_count with the server-tracked
            # count. This prevents a delegate from replaying a token by always
            # sending use_count=0 in the wire payload.
            token.use_count = self._token_use_counts.get(token.token_id, 0)
            if not token.is_valid():
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"error": "delegation_token_exhausted", "message": "Token expired or use limit reached."},
                    context={"in_reply_to": msg.id},
                )

            # Bind check: the presenting agent must be the named delegate.
            # This prevents token theft — if Bob's token is stolen by Mallory,
            # Mallory cannot present it because her DID won't match token.delegate_did.
            if token.delegate_did != msg.from_identity.did:
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"error": "delegation_token_unauthorized", "message": "Token was not issued to this agent."},
                    context={"in_reply_to": msg.id},
                )

            # Ed25519 signature verification on the delegation token.
            # The delegator's public key is obtained ONLY from the message's from_identity
            # when the sender IS the delegator (sender DID == delegator DID). We never
            # accept a public key from msg.context — that field is attacker-controlled and
            # would allow a confused-deputy attack (attacker supplies their own key to
            # verify a token they forged).
            #
            # When the sender is not the delegator (normal 3-party delegation: Alice → Bob
            # → Charlie), we cannot verify without a DID resolver (C-3). In that case we
            # reject rather than silently trust an unverifiable token. Once DID resolution
            # is implemented, look up token.delegator_did and always verify.
            delegator_public_key: Optional[str] = None
            if msg.from_identity.did == token.delegator_did:
                delegator_public_key = msg.from_identity.public_key

            if delegator_public_key:
                try:
                    if not verify_token(token, delegator_public_key):
                        return ROARMessage(
                            **{"from": self._identity, "to": msg.from_identity},
                            intent=MessageIntent.RESPOND,
                            payload={"error": "invalid_delegation_signature", "message": "Delegation token signature verification failed."},
                            context={"in_reply_to": msg.id},
                        )
                except ImportError:
                    # cryptography package not installed — skip Ed25519 verification
                    pass
            elif msg.from_identity.did != token.delegator_did:
                # Sender is not the delegator AND we have no DID resolver yet.
                # Reject rather than silently accept an unverifiable token.
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"error": "delegation_unverifiable", "message": "Cannot verify delegation token: delegator key not resolvable. Direct issuance (sender == delegator) required until DID resolution is supported."},
                    context={"in_reply_to": msg.id},
                )

            # Increment server-tracked count atomically (single-threaded coroutine).
            self._token_use_counts[token.token_id] = token.use_count + 1

        handler = self._handlers.get(msg.intent)
        if handler is None:
            logger.warning("No handler for intent '%s' from %s", msg.intent, msg.from_identity.did)
            return ROARMessage(
                **{"from": self._identity, "to": msg.from_identity},
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
        server_ref = self

        # Replay-protection guard (bounded; see dedup.py for eviction details).
        from .dedup import IdempotencyGuard as _IdempotencyGuard
        _serve_dedup = _IdempotencyGuard(max_keys=10_000, ttl_seconds=600.0)

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
                msg = ROARMessage(**body)
            except Exception:
                # Do not surface parse/validation details — they may expose schema info
                return JSONResponse(
                    {"error": "invalid_message", "message": "Request body is not a valid ROAR message."},
                    status_code=400,
                )

            if server_ref._signing_secret:
                if not msg.verify(server_ref._signing_secret, max_age_seconds=300):
                    return JSONResponse(
                        {"error": "invalid_signature", "message": "HMAC verification failed"},
                        status_code=401,
                    )

            # Replay protection — reject messages with a previously seen ID.
            if _serve_dedup.is_duplicate(msg.id):
                return JSONResponse(
                    {"error": "duplicate_message", "message": "Message already processed."},
                    status_code=409,
                )

            response = await server_ref.handle_message(msg)
            return response.model_dump(by_alias=True)

        @app.get("/roar/agents")
        async def list_agents():
            return {"agents": [server_ref.get_card().model_dump()]}

        logger.info(
            "ROAR server '%s' starting on http://%s:%d",
            self._identity.display_name,
            self._host,
            self._port,
        )
        uvicorn.run(app, host=self._host, port=self._port, log_level="warning")
