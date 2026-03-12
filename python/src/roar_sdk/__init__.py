# -*- coding: utf-8 -*-
"""ROAR Protocol — Python SDK.

Standalone implementation of the 5-layer agent communication standard.
Design: @kdairatchi — https://github.com/ProwlrBot/roar-protocol

Quick start::

    from roar_sdk import AgentIdentity, ROARMessage, MessageIntent, ROARClient, ROARServer

    # Layer 1: Identity
    identity = AgentIdentity(display_name="my-agent", capabilities=["code"])
    print(identity.did)  # did:roar:agent:my-agent-a1b2c3d4...

    # Layer 4: Exchange — build and sign a message
    msg = ROARMessage(
        **{"from": identity, "to": other_identity},
        intent=MessageIntent.DELEGATE,
        payload={"task": "review"},
    )
    msg.sign("shared-secret")

    # Layer 3: Connect — send over HTTP
    client = ROARClient(identity, signing_secret="shared-secret")
    response = await client.send_remote(
        to_agent_id=other_identity.did,
        intent=MessageIntent.DELEGATE,
        content={"task": "review"},
    )
"""

__version__ = "0.2.0"
__author__ = "kdairatchi"
__spec_version__ = "0.2.0"

from .types import (
    # Layer 1
    AgentIdentity,
    AgentCapability,
    AgentCard,
    # Layer 2
    DiscoveryEntry,
    AgentDirectory,
    # Layer 3
    TransportType,
    ConnectionConfig,
    # Layer 4
    MessageIntent,
    ROARMessage,
    # Layer 5
    StreamEventType,
    StreamEvent,
    # Adapters
    MCPAdapter,
    A2AAdapter,
)
from .client import ROARClient
from .server import ROARServer
from .streaming import EventBus, StreamFilter, Subscription

__all__ = [
    # Layer 1
    "AgentIdentity",
    "AgentCapability",
    "AgentCard",
    # Layer 2
    "DiscoveryEntry",
    "AgentDirectory",
    # Layer 3
    "TransportType",
    "ConnectionConfig",
    # Layer 4
    "MessageIntent",
    "ROARMessage",
    # Layer 5
    "StreamEventType",
    "StreamEvent",
    # Adapters
    "MCPAdapter",
    "A2AAdapter",
    # Client / Server
    "ROARClient",
    "ROARServer",
    # Streaming
    "EventBus",
    "StreamFilter",
    "Subscription",
]
