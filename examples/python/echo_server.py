#!/usr/bin/env python3
"""ROAR Protocol — Echo Server Example.

A minimal ROARServer that accepts DELEGATE messages and echoes them back.
Demonstrates Layer 1 (identity), Layer 4 (exchange), and Layer 2 (discovery registration).

Run this first, then run client.py in a second terminal.

Requirements:
    pip install -e ".[dev]"  (from the prowlrbot repo)
    pip install uvicorn fastapi  (for the HTTP server)

Usage:
    python3 examples/python/echo_server.py
"""

import asyncio
import logging

# ── Imports from ProwlrBot's ROAR reference implementation ──────────────────
from prowlrbot.protocols.roar import (
    AgentIdentity,
    MessageIntent,
    ROARMessage,
    StreamEvent,
    StreamEventType,
)
from prowlrbot.protocols.sdk.server import ROARServer

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("echo-server")

# ── Step 1: Give this server an identity ────────────────────────────────────
identity = AgentIdentity(
    display_name="echo-server",
    agent_type="agent",
    capabilities=["echo", "reflect"],
)
log.info("Server DID: %s", identity.did)

# ── Step 2: Create the server ───────────────────────────────────────────────
server = ROARServer(
    identity=identity,
    host="127.0.0.1",
    port=8089,
    description="Echoes DELEGATE messages back to the sender",
    signing_secret="roar-example-shared-secret",
)


# ── Step 3: Register a handler for DELEGATE messages ────────────────────────
@server.on(MessageIntent.DELEGATE)
async def handle_delegate(msg: ROARMessage) -> ROARMessage:
    log.info(
        "← DELEGATE from %s: %s",
        msg.from_identity.display_name,
        msg.payload,
    )

    # Emit a StreamEvent so any subscriber can see this happened
    await server.emit(
        StreamEvent(
            type=StreamEventType.TASK_UPDATE,
            source=identity.did,
            session_id=msg.context.get("session_id", ""),
            data={"status": "echoed", "original_payload": msg.payload},
        )
    )

    response = ROARMessage(
        **{"from": server.identity, "to": msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={"echo": msg.payload, "status": "ok"},
        context={"in_reply_to": msg.id},
    )
    log.info("→ RESPOND: %s", response.payload)
    return response


# ── Step 4: Expose the handler over HTTP using FastAPI ───────────────────────
def create_app():
    """Create a FastAPI app that routes POST /roar/message to the server."""
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError("Install fastapi: pip install fastapi uvicorn")

    app = FastAPI(title="ROAR Echo Server")

    @app.post("/roar/message")
    async def receive_message(request: Request):
        body = await request.json()
        msg = ROARMessage(**body)

        # Verify HMAC signature (disable age check for demo)
        if msg.auth and not msg.verify("roar-example-shared-secret", max_age_seconds=0):
            return JSONResponse({"error": "invalid_signature"}, status_code=401)

        response = await server.handle_message(msg)
        return response.model_dump(by_alias=True)

    @app.get("/roar/agents")
    async def list_agents():
        card = server.get_card()
        return {"agents": [card.model_dump()]}

    return app


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError:
        print("Install uvicorn: pip install uvicorn")
        raise

    log.info("Starting ROAR echo server on http://127.0.0.1:8089")
    log.info("Endpoints:")
    log.info("  POST /roar/message  — receive a ROARMessage")
    log.info("  GET  /roar/agents   — see this server's AgentCard")
    log.info("")
    log.info("Now run: python3 examples/python/client.py")

    uvicorn.run(create_app(), host="127.0.0.1", port=8089, log_level="warning")
