#!/usr/bin/env python3
"""Quickstart 01: Create an agent identity and handle messages.

Run: python 01_hello_agent.py
"""
import asyncio
from roar_sdk import AgentIdentity, MessageIntent, ROARMessage, ROARServer

# Create an agent identity (Layer 1)
identity = AgentIdentity(
    display_name="hello-agent",
    agent_type="agent",
    capabilities=["greeting"],
)
print(f"Agent DID: {identity.did}")

# Create a server (Layer 3+4)
server = ROARServer(
    identity=identity,
    host="127.0.0.1",
    port=8089,
    signing_secret="quickstart-secret",
)


# Register a handler for DELEGATE messages
@server.on(MessageIntent.DELEGATE)
async def handle(msg: ROARMessage) -> ROARMessage:
    print(f"Received from {msg.from_identity.display_name}: {msg.payload}")
    return ROARMessage(
        **{"from": identity, "to": msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={"greeting": "Hello from ROAR!", "received": msg.payload},
    )


if __name__ == "__main__":
    print("Starting on http://127.0.0.1:8089")
    print("  POST /roar/message  — send a message")
    print("  GET  /roar/health   — health check")
    server.serve()
