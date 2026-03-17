#!/usr/bin/env python3
"""ROAR Protocol Demo — Agent A (the "coder" agent).

Run this in Terminal 2 AFTER hub.py is running.
Agent A:
  1. Registers with the hub (challenge-response)
  2. Starts an HTTP server to receive messages
  3. Waits for messages from other agents

Usage:
    python examples/demo/agent_a.py
"""
import asyncio
import logging
import sys, io
import httpx

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from roar_sdk import (
    AgentIdentity,
    AgentCard,
    AgentCapability,
    MessageIntent,
    ROARMessage,
    ROARServer,
)
from roar_sdk.signing import generate_keypair, sign_ed25519

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("agent-a")

HUB_URL = "http://127.0.0.1:8090"
AGENT_PORT = 8091
SECRET = "demo-shared-secret"

# Generate Ed25519 keypair for identity
PRIV_KEY, PUB_KEY = generate_keypair()

# Create identity
identity = AgentIdentity(
    display_name="agent-a-coder",
    agent_type="agent",
    capabilities=["code-review", "python", "debugging"],
    public_key=PUB_KEY,
)

print(f"""
╔══════════════════════════════════════════════════════════════╗
║                      AGENT A — CODER                        ║
╠══════════════════════════════════════════════════════════════╣
║  DID: {identity.did[:52]}...
║  Capabilities: code-review, python, debugging               ║
║  Port: {AGENT_PORT}                                                  ║
╚══════════════════════════════════════════════════════════════╝
""")


async def register_with_hub():
    """Register this agent with the discovery hub via challenge-response."""
    import base64
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    card = AgentCard(
        identity=identity,
        description="Coder agent — reviews code and debugs issues",
        skills=["code-review", "python", "debugging"],
        channels=["http"],
        endpoints={"http": f"http://127.0.0.1:{AGENT_PORT}"},
        declared_capabilities=[
            AgentCapability(name="code-review", description="Reviews code for bugs"),
            AgentCapability(name="python", description="Writes Python code"),
        ],
    )

    async with httpx.AsyncClient() as client:
        # Step 1: Request challenge
        log.info("[HUB] Requesting registration challenge...")
        r = await client.post(f"{HUB_URL}/roar/agents/register", json={
            "did": identity.did,
            "public_key": PUB_KEY,
            "card": card.model_dump(),
        })
        challenge = r.json()
        log.info("[HUB] Got challenge: %s (expires in 30s)", challenge["challenge_id"][:16])

        # Step 2: Sign the nonce and complete registration
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(PRIV_KEY))
        sig_bytes = private.sign(challenge["nonce"].encode())
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

        r = await client.post(f"{HUB_URL}/roar/agents/challenge", json={
            "challenge_id": challenge["challenge_id"],
            "signature": f"ed25519:{sig_b64}",
        })
        result = r.json()
        if result.get("registered"):
            log.info("[HUB] Registered successfully with hub!")
        else:
            log.error("[HUB] Registration failed: %s", result)
            return False

        # Verify we're listed
        r = await client.get(f"{HUB_URL}/roar/agents")
        agents = r.json().get("agents", [])
        log.info("[HUB] Hub now has %d registered agent(s)", len(agents))
        return True


# Create server to receive messages
server = ROARServer(
    identity=identity,
    host="127.0.0.1",
    port=AGENT_PORT,
    description="Coder agent — reviews code and debugs issues",
    signing_secret=SECRET,
)


@server.on(MessageIntent.DELEGATE)
async def handle_delegate(msg: ROARMessage) -> ROARMessage:
    log.info("")
    log.info("=" * 60)
    log.info("INCOMING MESSAGE from %s", msg.from_identity.display_name)
    log.info("  Intent:  %s", msg.intent)
    log.info("  Payload: %s", msg.payload)
    log.info("=" * 60)

    # Respond
    response = ROARMessage(
        **{"from": identity, "to": msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={
            "review": "Code looks good! Found 0 issues.",
            "status": "approved",
            "reviewer": identity.display_name,
        },
        context={"in_reply_to": msg.id},
    )
    log.info("Sending response: %s", response.payload)
    return response


@server.on(MessageIntent.ASK)
async def handle_ask(msg: ROARMessage) -> ROARMessage:
    log.info("")
    log.info("QUESTION from %s: %s", msg.from_identity.display_name, msg.payload)
    return ROARMessage(
        **{"from": identity, "to": msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={"answer": "42", "from": identity.display_name},
        context={"in_reply_to": msg.id},
    )


if __name__ == "__main__":
    # Register with hub, then start server
    loop = asyncio.new_event_loop()
    registered = loop.run_until_complete(register_with_hub())
    if not registered:
        exit(1)

    log.info("")
    log.info("Agent A listening on http://127.0.0.1:%d", AGENT_PORT)
    log.info("Waiting for messages from other agents...")
    log.info("Now start agent_b.py in another terminal!")
    log.info("")
    server.serve()
