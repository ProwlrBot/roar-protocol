#!/usr/bin/env python3
"""ROAR Protocol — Client Example.

Connects to the echo server (examples/python/echo_server.py), registers itself,
and sends a DELEGATE message.

Demonstrates:
  Layer 1 — creating an AgentIdentity
  Layer 2 — registering an AgentCard with the directory
  Layer 3 — connecting via HTTP transport
  Layer 4 — building, signing, and sending a ROARMessage

Requirements:
    pip install -e "python/[dev]"  (from the roar-protocol repo)
    pip install httpx

Usage:
    # Terminal 1: start the echo server
    python3 examples/python/echo_server.py

    # Terminal 2: run this client
    python3 examples/python/client.py
"""

import asyncio
import logging
import os

# ── Imports from the standalone roar-sdk package ────────────────────────────
from roar_sdk import (
    AgentCard,
    AgentIdentity,
    MessageIntent,
    ROARMessage,
    ROARClient,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("roar-client")

# Server details — point at echo_server.py or prowlr app (:8088)
SERVER_URL = "http://127.0.0.1:8089"
SHARED_SECRET = os.environ.get("ROAR_SIGNING_SECRET", "")


async def main() -> None:
    # ── Step 1: Create an identity for this client ───────────────────────────
    identity = AgentIdentity(
        display_name="example-client",
        agent_type="agent",
        capabilities=["demo", "testing"],
    )
    log.info("Client DID: %s", identity.did)

    # ── Step 2: Create a ROARClient ──────────────────────────────────────────
    client = ROARClient(identity, signing_secret=SHARED_SECRET)

    # ── Step 3: Register the server in the local directory ───────────────────
    # In production, you'd call GET /roar/agents to fetch the server's card.
    # For this demo we construct it manually.
    server_identity = AgentIdentity(
        did="did:roar:agent:echo-server-00000000000000000",
        display_name="echo-server",
        agent_type="agent",
        capabilities=["echo", "reflect"],
    )
    server_card = AgentCard(
        identity=server_identity,
        description="Echoes DELEGATE messages back",
        endpoints={"http": SERVER_URL},
    )
    client.register(
        AgentCard(identity=identity, description="Example client")
    )
    client.directory.register(server_card)

    log.info("Sending DELEGATE to %s ...", SERVER_URL)

    # ── Step 4: Send a DELEGATE message and wait for the response ────────────
    try:
        response = await client.send_remote(
            to_agent_id=server_identity.did,
            intent=MessageIntent.DELEGATE,
            content={"task": "hello from ROAR client", "data": [1, 2, 3]},
            context={"session_id": "demo-session"},
        )
        log.info("✅ Response received:")
        log.info("   intent  : %s", response.intent)
        log.info("   payload : %s", response.payload)
        log.info("   from    : %s", response.from_identity.display_name)

    except ConnectionError as e:
        log.error("Connection failed: %s", e)
        log.error("Is echo_server.py running? python3 examples/python/echo_server.py")
        raise

    # ── Step 5: Demonstrate local message construction without sending ────────
    log.info("")
    log.info("Local message construction (no network):")
    msg = client.send(
        to_agent_id=server_identity.did,
        intent=MessageIntent.NOTIFY,
        content={"note": "ping"},
    )
    log.info("   id        : %s", msg.id)
    log.info("   intent    : %s", msg.intent)
    log.info("   signed    : %s", bool(msg.auth.get("signature")))
    log.info("   verify    : %s", msg.verify(SHARED_SECRET, max_age_seconds=300))


if __name__ == "__main__":
    asyncio.run(main())
