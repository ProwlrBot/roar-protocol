#!/usr/bin/env python3
"""Quickstart 02: Register agents, discover by capability, send a message.

Run: python 02_discover_and_talk.py
"""
import asyncio
from roar_sdk import (
    AgentIdentity,
    AgentCard,
    AgentDirectory,
    MessageIntent,
    ROARMessage,
)

# Create two agents (Layer 1)
coder = AgentIdentity(display_name="coder", capabilities=["code-review", "python"])
reviewer = AgentIdentity(display_name="reviewer", capabilities=["code-review"])

# Register them in a directory (Layer 2)
directory = AgentDirectory()
directory.register(AgentCard(identity=coder, description="Writes Python code"))
directory.register(AgentCard(identity=reviewer, description="Reviews code"))

# Discover agents with "code-review" capability
results = directory.search("code-review")
print(f"Found {len(results)} agents with 'code-review':")
for entry in results:
    print(f"  - {entry.agent_card.identity.display_name} ({entry.agent_card.identity.did})")

# Send a message from coder to reviewer (Layer 4)
msg = ROARMessage(
    **{"from": coder, "to": reviewer},
    intent=MessageIntent.DELEGATE,
    payload={"task": "review", "file": "main.py", "lines": "42-58"},
    context={"priority": "high"},
)

# Sign with HMAC-SHA256
msg.sign("shared-secret")
print(f"\nSigned message ID: {msg.id}")
print(f"Signature: {msg.auth.get('signature', '')[:40]}...")

# Verify
assert msg.verify("shared-secret"), "Signature verification failed!"
print("Signature verified successfully.")
