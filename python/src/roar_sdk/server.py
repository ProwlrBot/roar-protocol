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
            if not token.is_valid():
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"error": "delegation_token_exhausted", "message": "Token expired or use limit reached."},
                    context={"in_reply_to": msg.id},
                )
            token.consume()

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

        @app.post("/roar/message")
        async def receive_message(request: Request):
            body = await request.json()
            msg = ROARMessage(**body)

            if server_ref._signing_secret and msg.auth:
                if not msg.verify(server_ref._signing_secret, max_age_seconds=300):
                    return JSONResponse(
                        {"error": "invalid_signature", "message": "HMAC verification failed"},
                        status_code=401,
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
