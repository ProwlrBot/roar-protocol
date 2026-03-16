# -*- coding: utf-8 -*-
"""ROAR Protocol SDK — Server for receiving and dispatching ROAR messages."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from .did_resolver import DIDResolutionError, resolve_did_to_public_key
from .streaming import EventBus
from .token_store import InMemoryTokenStore, TokenStore
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
        # Use RedisTokenStore for multi-worker deployments (see token_store.py).
        self._token_store: TokenStore = token_store or InMemoryTokenStore()

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

            # SECURITY INVARIANT 1: bind check MUST run before signature verification.
            # Ensures the token was issued to this exact sender — prevents token theft.
            if token.delegate_did != msg.from_identity.did:
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"error": "delegation_token_unauthorized", "message": "Token was not issued to this agent."},
                    context={"in_reply_to": msg.id},
                )

            # Expiry check (before consuming a use from the store)
            if token.expires_at is not None:
                import time
                if time.time() > token.expires_at:
                    return ROARMessage(
                        **{"from": self._identity, "to": msg.from_identity},
                        intent=MessageIntent.RESPOND,
                        payload={"error": "delegation_token_exhausted", "message": "Token expired or use limit reached."},
                        context={"in_reply_to": msg.id},
                    )

            # Atomic use-count check + increment via the configured store.
            if not self._token_store.get_and_increment(token.token_id, token.max_uses):
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"error": "delegation_token_exhausted", "message": "Token expired or use limit reached."},
                    context={"in_reply_to": msg.id},
                )

            # Determine the delegator's public key for signature verification.
            # SECURITY INVARIANT 2: NEVER use context["delegator_public_key"] —
            # that field is attacker-controlled and accepting it would allow a
            # confused-deputy attack (attacker supplies their own key to verify a forged token).
            if msg.from_identity.did == token.delegator_did:
                # Same-party delegation: sender IS the delegator, use their key directly.
                delegator_public_key = msg.from_identity.public_key
                if not delegator_public_key:
                    return ROARMessage(
                        **{"from": self._identity, "to": msg.from_identity},
                        intent=MessageIntent.RESPOND,
                        payload={
                            "error": "delegation_unverifiable",
                            "message": "No public key available for delegator DID.",
                        },
                        context={"in_reply_to": msg.id},
                    )
            else:
                # 3-party delegation: resolve the delegator's DID to get their key.
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
                        **{"from": self._identity, "to": msg.from_identity},
                        intent=MessageIntent.RESPOND,
                        payload={
                            "error": "delegation_unverifiable",
                            "message": f"Could not resolve delegator DID: {exc}",
                        },
                        context={"in_reply_to": msg.id},
                    )

            try:
                if not verify_token(token, delegator_public_key):
                    return ROARMessage(
                        **{"from": self._identity, "to": msg.from_identity},
                        intent=MessageIntent.RESPOND,
                        payload={
                            "error": "invalid_delegation_signature",
                            "message": "Delegation token signature verification failed.",
                        },
                        context={"in_reply_to": msg.id},
                    )
            except ImportError:
                # cryptography package not installed — skip Ed25519 verification
                pass

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

            # C-1 fix: check signing_secret alone — empty auth must not bypass HMAC.
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
