# -*- coding: utf-8 -*-
"""ROAR Protocol — canonical type definitions.

This is the single source of truth for all wire format types.
All SDKs (TypeScript, Go, etc.) must produce identical JSON for these types.

Layers:
  1 — Identity:   AgentIdentity, AgentCapability, AgentCard
  2 — Discovery:  DiscoveryEntry, AgentDirectory
  3 — Connect:    TransportType, ConnectionConfig
  4 — Exchange:   MessageIntent, ROARMessage
  5 — Stream:     StreamEventType, StreamEvent
  Adapters:       MCPAdapter, A2AAdapter
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ._compat import StrEnum

# ---------------------------------------------------------------------------
# Layer 1: Identity
# ---------------------------------------------------------------------------


class AgentIdentity(BaseModel):
    """W3C DID-based agent identity. Every ROAR agent has one.

    The ``did`` field is auto-generated if not provided:
    ``did:roar:<agent_type>:<slug>-<16-char hex>``
    """

    did: str = ""
    display_name: str = ""
    agent_type: str = "agent"  # agent | tool | human | ide
    capabilities: List[str] = Field(default_factory=list)
    version: str = "1.0"
    public_key: Optional[str] = None  # Ed25519 public key, hex-encoded

    def model_post_init(self, __context: Any) -> None:
        if not self.did:
            uid = uuid.uuid4().hex[:16]
            slug = self.display_name.lower().replace(" ", "-")[:20] or "agent"
            self.did = f"did:roar:{self.agent_type}:{slug}-{uid}"


class AgentCapability(BaseModel):
    """Formal capability declaration with input/output schemas."""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)


class AgentCard(BaseModel):
    """Public capability descriptor — an agent's business card for discovery."""

    identity: AgentIdentity
    description: str = ""
    skills: List[str] = Field(default_factory=list)
    channels: List[str] = Field(default_factory=list)
    endpoints: Dict[str, str] = Field(default_factory=dict)
    declared_capabilities: List[AgentCapability] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    attestation: Optional[str] = None  # base64url Ed25519 signature over canonical card JSON


# ---------------------------------------------------------------------------
# Layer 2: Discovery
# ---------------------------------------------------------------------------


class DiscoveryEntry(BaseModel):
    """An agent registered in a discovery directory."""

    agent_card: AgentCard
    registered_at: float = Field(default_factory=time.time)
    last_seen: float = Field(default_factory=time.time)
    hub_url: str = ""  # Which hub registered this agent


class AgentDirectory:
    """In-memory agent directory. Register, lookup, and search by capability."""

    def __init__(self) -> None:
        self._agents: Dict[str, DiscoveryEntry] = {}

    def register(self, card: AgentCard) -> DiscoveryEntry:
        entry = DiscoveryEntry(agent_card=card)
        self._agents[card.identity.did] = entry
        return entry

    def unregister(self, did: str) -> bool:
        return self._agents.pop(did, None) is not None

    def lookup(self, did: str) -> Optional[DiscoveryEntry]:
        return self._agents.get(did)

    def search(self, capability: str) -> List[DiscoveryEntry]:
        """Find agents that declare a specific capability string."""
        return [
            entry
            for entry in self._agents.values()
            if capability in entry.agent_card.identity.capabilities
        ]

    def list_all(self) -> List[DiscoveryEntry]:
        return list(self._agents.values())


# ---------------------------------------------------------------------------
# Layer 3: Connect
# ---------------------------------------------------------------------------


class TransportType(StrEnum):
    STDIO = "stdio"
    HTTP = "http"
    WEBSOCKET = "websocket"
    GRPC = "grpc"


class ConnectionConfig(BaseModel):
    """Connection configuration for a ROAR endpoint."""

    transport: TransportType = TransportType.HTTP
    url: str = ""
    auth_method: str = "hmac"  # hmac | jwt | mtls | none
    secret: str = ""
    timeout_ms: int = 30000


# ---------------------------------------------------------------------------
# Layer 4: Exchange
# ---------------------------------------------------------------------------


class MessageIntent(StrEnum):
    """What the sender wants the receiver to do."""

    EXECUTE = "execute"    # Agent → Tool: run a tool or command
    DELEGATE = "delegate"  # Agent → Agent: hand off a task
    UPDATE = "update"      # Agent → IDE: report progress
    ASK = "ask"            # Agent → Human: request input or approval
    RESPOND = "respond"    # Any → Any: reply to any message
    NOTIFY = "notify"      # Any → Any: one-way notification
    DISCOVER = "discover"  # Any → Directory: find agents by capability


class ROARMessage(BaseModel):
    """Unified ROAR message — one format for all agent communication.

    Use ``sign(secret)`` to add HMAC-SHA256 auth.
    Use ``verify(secret)`` to authenticate an incoming message.

    Wire format uses ``from``/``to`` as field names (Python aliases for
    ``from_identity``/``to_identity`` to avoid the ``from`` keyword conflict).
    """

    roar: str = "1.0"
    id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:10]}")
    from_identity: AgentIdentity = Field(alias="from")
    to_identity: AgentIdentity = Field(alias="to")
    intent: MessageIntent
    payload: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    auth: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)

    model_config = {"populate_by_name": True}

    def _signing_body(self) -> str:
        """Canonical JSON body for HMAC signing.

        Covers all security-relevant fields. Keys are sorted alphabetically
        to ensure deterministic output across languages.

        The golden value for this body is in:
          tests/conformance/golden/signature.json
        """
        return json.dumps(
            {
                "id": self.id,
                "from": self.from_identity.did,
                "to": self.to_identity.did,
                "intent": self.intent,
                "payload": self.payload,
                "context": self.context,
                "timestamp": self.auth.get("timestamp", self.timestamp),
            },
            sort_keys=True,
        )

    def sign(self, secret: str) -> "ROARMessage":
        """Add HMAC-SHA256 signature. Returns self for chaining."""
        now = time.time()
        self.auth = {"timestamp": now}
        body = self._signing_body()
        sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        self.auth["signature"] = f"hmac-sha256:{sig}"
        return self

    def verify(self, secret: str, max_age_seconds: float = 300.0) -> bool:
        """Verify HMAC signature with replay protection.

        Args:
            secret: The shared signing secret.
            max_age_seconds: Maximum message age in seconds. Set to 0 to skip.

        Returns:
            True if signature is valid and message is within the time window.
        """
        sig_value = self.auth.get("signature", "")
        if not sig_value.startswith("hmac-sha256:"):
            return False

        if max_age_seconds > 0:
            msg_time = self.auth.get("timestamp", 0)
            if abs(time.time() - msg_time) > max_age_seconds:
                return False

        expected = sig_value.split(":", 1)[1]
        body = self._signing_body()
        actual = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, actual)


# ---------------------------------------------------------------------------
# Layer 5: Stream
# ---------------------------------------------------------------------------


class StreamEventType(StrEnum):
    TOOL_CALL = "tool_call"
    MCP_REQUEST = "mcp_request"
    REASONING = "reasoning"
    TASK_UPDATE = "task_update"
    MONITOR_ALERT = "monitor_alert"
    AGENT_STATUS = "agent_status"
    CHECKPOINT = "checkpoint"
    WORLD_UPDATE = "world_update"  # AgentVerse


class StreamEvent(BaseModel):
    """A real-time streaming event published via SSE or WebSocket."""

    type: StreamEventType
    source: str = ""       # DID of the emitting agent
    session_id: str = ""
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Protocol Adapters
# ---------------------------------------------------------------------------


class MCPAdapter:
    """Translate between MCP tool calls and ROAR messages."""

    @staticmethod
    def mcp_to_roar(
        tool_name: str,
        params: Dict[str, Any],
        from_agent: AgentIdentity,
    ) -> ROARMessage:
        tool_identity = AgentIdentity(display_name=tool_name, agent_type="tool")
        hdr: Dict[str, Any] = {"from": from_agent, "to": tool_identity}
        return ROARMessage(
            **hdr,
            intent=MessageIntent.EXECUTE,
            payload={"action": tool_name, "params": params},
        )

    @staticmethod
    def roar_to_mcp(msg: ROARMessage) -> Dict[str, Any]:
        return {
            "tool": msg.payload.get("action", ""),
            "params": msg.payload.get("params", {}),
        }


class A2AAdapter:
    """Translate between A2A agent tasks and ROAR messages."""

    @staticmethod
    def a2a_task_to_roar(
        task: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
    ) -> ROARMessage:
        hdr: Dict[str, Any] = {"from": from_agent, "to": to_agent}
        return ROARMessage(
            **hdr,
            intent=MessageIntent.DELEGATE,
            payload=task,
            context={"protocol": "a2a"},
        )

    @staticmethod
    def roar_to_a2a(msg: ROARMessage) -> Dict[str, Any]:
        return {
            "task_id": msg.id,
            "from": msg.from_identity.did,
            "to": msg.to_identity.did,
            "payload": msg.payload,
        }
