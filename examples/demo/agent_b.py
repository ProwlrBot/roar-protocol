#!/usr/bin/env python3
"""ROAR Protocol Demo — Agent B (the "tester" agent).

Run this in Terminal 3 AFTER hub.py and agent_a.py are running.
Agent B:
  1. Registers with the hub
  2. Discovers Agent A by searching for "code-review" capability
  3. Sends a DELEGATE message to Agent A
  4. Receives and displays the response

Usage:
    python examples/demo/agent_b.py
"""
import asyncio
import base64
import logging
import os
import sys, io
import httpx
import json

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from roar_sdk import (
    AgentIdentity,
    AgentCard,
    AgentCapability,
    MessageIntent,
    ROARMessage,
    ROARClient,
)
from roar_sdk.signing import generate_keypair

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s  %(message)s")
log = logging.getLogger("agent-b")

HUB_URL = "http://127.0.0.1:8090"
SECRET = os.environ.get("ROAR_SIGNING_SECRET", "")

# Generate Ed25519 keypair
PRIV_KEY, PUB_KEY = generate_keypair()

# Create identity
identity = AgentIdentity(
    display_name="agent-b-tester",
    agent_type="agent",
    capabilities=["testing", "qa"],
    public_key=PUB_KEY,
)

print(f"""
╔══════════════════════════════════════════════════════════════╗
║                     AGENT B — TESTER                        ║
╠══════════════════════════════════════════════════════════════╣
║  DID: {identity.did[:52]}...
║  Capabilities: testing, qa                                   ║
╚══════════════════════════════════════════════════════════════╝
""")


async def register_with_hub():
    """Register this agent with the hub."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    card = AgentCard(
        identity=identity,
        description="Tester agent — runs QA and testing",
        skills=["testing", "qa"],
        channels=["http"],
        endpoints={},
        declared_capabilities=[
            AgentCapability(name="testing", description="Runs test suites"),
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
        log.info("[HUB] Got challenge: %s", challenge["challenge_id"][:16])

        # Step 2: Sign and complete
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(PRIV_KEY))
        sig_bytes = private.sign(challenge["nonce"].encode())
        sig_b64 = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

        r = await client.post(f"{HUB_URL}/roar/agents/challenge", json={
            "challenge_id": challenge["challenge_id"],
            "signature": f"ed25519:{sig_b64}",
        })
        result = r.json()
        if result.get("registered"):
            log.info("[HUB] Registered successfully!")
        else:
            log.error("[HUB] Registration failed: %s", result)
            return False
        return True


async def discover_agents():
    """Query the hub to find agents with code-review capability."""
    async with httpx.AsyncClient() as client:
        log.info("")
        log.info("=" * 60)
        log.info("DISCOVERING AGENTS via Hub...")
        log.info("=" * 60)

        # List all agents
        r = await client.get(f"{HUB_URL}/roar/agents")
        all_agents = r.json().get("agents", [])
        log.info("[HUB] Total agents registered: %d", len(all_agents))
        for agent in all_agents:
            card = agent.get("agent_card", {})
            ident = card.get("identity", {})
            log.info("  - %s (%s)", ident.get("display_name"), ident.get("did", "")[:40])
            log.info("    capabilities: %s", ident.get("capabilities", []))

        # Search by capability
        log.info("")
        log.info("Searching for agents with 'code-review' capability...")
        r = await client.get(f"{HUB_URL}/roar/agents", params={"capability": "code-review"})
        results = r.json().get("agents", [])
        log.info("Found %d agent(s) with 'code-review'", len(results))

        return results


async def send_message(target_card: dict):
    """Send a DELEGATE message to the discovered agent."""
    target_identity = target_card.get("agent_card", {}).get("identity", {})
    target_endpoints = target_card.get("agent_card", {}).get("endpoints", {})
    target_url = target_endpoints.get("http", "")
    target_did = target_identity.get("did", "")
    target_name = target_identity.get("display_name", "unknown")

    if not target_url:
        log.error("No HTTP endpoint found for %s", target_name)
        return

    log.info("")
    log.info("=" * 60)
    log.info("SENDING MESSAGE to %s", target_name)
    log.info("  URL: %s", target_url)
    log.info("  DID: %s", target_did[:50])
    log.info("=" * 60)

    # Build the message
    to_identity = AgentIdentity(
        did=target_did,
        display_name=target_name,
        capabilities=target_identity.get("capabilities", []),
    )

    msg = ROARMessage(
        **{"from": identity, "to": to_identity},
        intent=MessageIntent.DELEGATE,
        payload={
            "task": "code-review",
            "file": "main.py",
            "description": "Please review my latest changes",
            "urgency": "high",
        },
        context={"session_id": "demo-session-001"},
    )
    msg.sign(SECRET)

    log.info("Message signed (HMAC-SHA256)")
    log.info("  ID: %s", msg.id)
    log.info("  Signature: %s...", msg.auth.get("signature", "")[:50])

    # Send via HTTP
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{target_url}/roar/message",
            json=msg.model_dump(by_alias=True),
            timeout=10,
        )

        if r.status_code == 200:
            response = r.json()
            log.info("")
            log.info("=" * 60)
            log.info("RESPONSE RECEIVED!")
            log.info("  From:    %s", response.get("from_identity", response.get("from", {})).get("display_name", "?"))
            log.info("  Intent:  %s", response.get("intent"))
            log.info("  Payload: %s", json.dumps(response.get("payload", {}), indent=2))
            log.info("=" * 60)
        else:
            log.error("Error %d: %s", r.status_code, r.text)


async def main():
    # Step 1: Register with hub
    registered = await register_with_hub()
    if not registered:
        return

    # Step 2: Discover agents
    agents = await discover_agents()

    # Step 3: Find one with code-review and send message
    target = None
    for agent in agents:
        card = agent.get("agent_card", {})
        ident = card.get("identity", {})
        if ident.get("did") != identity.did:  # Don't talk to ourselves
            if "code-review" in ident.get("capabilities", []):
                target = agent
                break

    if target:
        await send_message(target)
    else:
        log.warning("No agents with 'code-review' capability found!")
        log.warning("Make sure agent_a.py is running.")

    print("""
╔══════════════════════════════════════════════════════════════╗
║                     DEMO COMPLETE!                          ║
║                                                             ║
║  What happened:                                             ║
║  1. Agent B registered with Hub (challenge-response)        ║
║  2. Agent B queried Hub for 'code-review' agents            ║
║  3. Hub returned Agent A's card with endpoint               ║
║  4. Agent B sent DELEGATE message to Agent A                ║
║  5. Agent A processed it and sent RESPOND back              ║
║  6. Agent B received the response                           ║
║                                                             ║
║  Both agents found each other through the Hub!              ║
╚══════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    asyncio.run(main())
