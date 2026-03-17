# -*- coding: utf-8 -*-
"""ROAR Protocol — Bridge Router for cross-protocol message routing.

The BridgeRouter accepts messages in any supported protocol format
(ROAR, MCP, A2A, ACP), translates them to ROAR's internal format,
routes them through a ROARHub, and translates responses back to the
caller's preferred protocol.

Supported protocols:
  - ROAR (native, pass-through)
  - MCP (JSON-RPC 2.0 with tools/* methods)
  - A2A (JSON-RPC 2.0 with tasks/* methods)
  - ACP (role/content session messages)

Usage::

    from roar_sdk.bridge import BridgeRouter
    from roar_sdk import ROARHub, AgentCard, AgentIdentity

    hub = ROARHub(port=8090)
    bridge = BridgeRouter(hub)

    # Register agents with protocol preferences
    card = AgentCard(identity=AgentIdentity(display_name="my-agent"))
    bridge.register_agent(card, preferred_protocol="a2a")

    # Bridge any incoming message
    response = bridge.bridge_message({"jsonrpc": "2.0", "method": "tasks/send", ...})
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, cast

from .adapters.detect import ProtocolType, detect_protocol
from .types import (
    AgentCard,
    AgentIdentity,
    AgentDirectory,
    DiscoveryEntry,
    MCPAdapter,
    A2AAdapter,
    MessageIntent,
    ROARMessage,
)

# Conditional imports for protocol-specific adapters
try:
    from .adapters.acp import ACPAdapter
    _ACP_AVAILABLE = True
except ImportError:
    _ACP_AVAILABLE = False

try:
    from .adapters import mcp as _mcp_module
    _MCP_ADAPTER_AVAILABLE = True
except (ImportError, AttributeError):
    _MCP_ADAPTER_AVAILABLE = False

try:
    from .adapters import a2a as _a2a_module
    _A2A_ADAPTER_AVAILABLE = True
except (ImportError, AttributeError):
    _A2A_ADAPTER_AVAILABLE = False

logger = logging.getLogger(__name__)


class BridgeRouter:
    """Cross-protocol bridge that routes messages through a ROAR hub.

    Wraps a ROARHub (or at least its AgentDirectory) and provides:
      - Protocol detection and translation
      - Agent registration with protocol preferences
      - Bidirectional message bridging (any protocol in, any protocol out)
    """

    def __init__(self, hub: Any) -> None:
        """Initialize the bridge router.

        Args:
            hub: A ROARHub instance or any object with a ``.directory`` attribute
                 that returns an AgentDirectory.
        """
        self._hub = hub
        self._directory: AgentDirectory = hub.directory
        # Map DID -> preferred protocol string
        self._protocol_preferences: Dict[str, str] = {}
        # Internal sender identity for bridge-originated messages
        self._bridge_identity = AgentIdentity(
            display_name="roar-bridge",
            agent_type="agent",
            capabilities=["bridge", "routing"],
        )

    @property
    def directory(self) -> AgentDirectory:
        """Access the underlying agent directory."""
        return self._directory

    def register_agent(
        self,
        card: AgentCard,
        preferred_protocol: str = "roar",
    ) -> DiscoveryEntry:
        """Register an agent with the hub and record its preferred protocol.

        Args:
            card: The agent's AgentCard.
            preferred_protocol: The protocol this agent prefers for communication.
                One of: "roar", "mcp", "a2a", "acp".

        Returns:
            The DiscoveryEntry created by the directory.
        """
        entry = self._directory.register(card)
        self._protocol_preferences[card.identity.did] = preferred_protocol.lower()
        logger.info(
            "Bridge registered agent %s (protocol=%s)",
            card.identity.did,
            preferred_protocol,
        )
        return entry

    def get_agent_protocol(self, did: str) -> str:
        """Look up an agent's preferred protocol.

        Args:
            did: The agent's DID.

        Returns:
            The preferred protocol string, or "roar" as default.
        """
        return self._protocol_preferences.get(did, "roar")

    def bridge_message(self, raw_message: dict) -> dict:
        """Accept a message in any protocol, translate, route, and respond.

        Flow:
          1. Detect the incoming protocol
          2. Translate to a ROAR message
          3. Route to the target agent via the hub directory
          4. Generate a response
          5. Translate the response to the target's preferred protocol

        Args:
            raw_message: The raw incoming message dict in any supported format.

        Returns:
            A response dict in the target agent's preferred protocol format.
            On error, returns ``{"error": ..., "protocol": "unknown"}``.
        """
        # Step 1: Detect protocol
        protocol = detect_protocol(raw_message)

        if protocol == ProtocolType.UNKNOWN:
            return {
                "error": "unknown_protocol",
                "detail": "Could not detect the protocol of the incoming message",
                "protocol": "unknown",
            }

        # Step 2: Translate to ROAR
        roar_msg = self._translate_to_roar(raw_message, protocol)
        if roar_msg is None:
            return {
                "error": "translation_failed",
                "detail": f"Failed to translate {protocol.value} message to ROAR format",
                "protocol": protocol.value,
            }

        # Step 3: Route — look up the target agent
        target_did = roar_msg.to_identity.did
        target_entry = self._directory.lookup(target_did) if target_did else None

        # Step 4: Generate response
        response_msg = self._generate_response(roar_msg, target_entry)

        # Step 5: Determine output protocol and translate back
        target_protocol = self._protocol_preferences.get(target_did, "roar")
        result = self._translate_from_roar(response_msg, target_protocol, raw_message)
        return result

    def _translate_to_roar(
        self,
        raw_message: dict,
        protocol: ProtocolType,
    ) -> Optional[ROARMessage]:
        """Translate an incoming message to ROAR format.

        Args:
            raw_message: The raw message dict.
            protocol: The detected protocol type.

        Returns:
            A ROARMessage, or None on translation failure.
        """
        try:
            if protocol == ProtocolType.ROAR:
                return self._translate_roar_native(raw_message)
            elif protocol == ProtocolType.MCP:
                return self._translate_mcp(raw_message)
            elif protocol == ProtocolType.A2A:
                return self._translate_a2a(raw_message)
            elif protocol == ProtocolType.ACP:
                return self._translate_acp(raw_message)
            else:
                logger.warning("No translator for protocol: %s", protocol.value)
                return None
        except Exception as exc:
            logger.error("Translation error for %s: %s", protocol.value, exc)
            return None

    def _translate_roar_native(self, raw_message: dict) -> ROARMessage:
        """Pass-through ROAR native messages with validation."""
        return ROARMessage.model_validate(raw_message)

    def _translate_mcp(self, raw_message: dict) -> ROARMessage:
        """Translate MCP JSON-RPC to ROAR."""
        method = raw_message.get("method", "")
        params = raw_message.get("params", {})

        # Extract tool name from MCP method
        if method == "tools/call":
            tool_name = params.get("name", "unknown-tool")
            tool_params = params.get("arguments", {})
        elif method.startswith("tools/"):
            tool_name = method
            tool_params = params
        else:
            tool_name = method
            tool_params = params

        # Use the core MCPAdapter
        return MCPAdapter.mcp_to_roar(
            tool_name=tool_name,
            params=tool_params,
            from_agent=self._bridge_identity,
        )

    def _translate_a2a(self, raw_message: dict) -> ROARMessage:
        """Translate A2A task to ROAR."""
        # A2A can come as JSON-RPC or raw task envelope
        if raw_message.get("jsonrpc") == "2.0":
            params = raw_message.get("params", {})
            task = params if params else raw_message
        else:
            task = raw_message

        # Extract target agent from task if available
        to_did = task.get("to", "")
        to_identity = AgentIdentity(did=to_did) if to_did else AgentIdentity(display_name="unknown")

        return A2AAdapter.a2a_task_to_roar(
            task=task,
            from_agent=self._bridge_identity,
            to_agent=to_identity,
        )

    def _translate_acp(self, raw_message: dict) -> ROARMessage:
        """Translate ACP message to ROAR."""
        if not _ACP_AVAILABLE:
            # Fallback: manually create ROAR message from ACP structure
            role = raw_message.get("role", "user")
            content = raw_message.get("content", "")
            intent = MessageIntent.ASK if role == "user" else MessageIntent.RESPOND
            return ROARMessage(
                **cast(Dict[str, Any], {
                    "from": self._bridge_identity,
                    "to": AgentIdentity(display_name="unknown"),
                }),
                intent=intent,
                payload={"content": content},
                context={"protocol": "acp"},
            )

        return ACPAdapter.acp_message_to_roar(
            acp_message=raw_message,
            from_agent=self._bridge_identity,
            to_agent=AgentIdentity(display_name="unknown"),
        )

    def _generate_response(
        self,
        roar_msg: ROARMessage,
        target_entry: Optional[DiscoveryEntry],
    ) -> ROARMessage:
        """Generate a response to a routed ROAR message.

        In a real deployment this would forward the message to the target
        agent's endpoint and await a response. Here we generate an
        acknowledgement that confirms routing was successful.

        Args:
            roar_msg: The incoming ROAR message.
            target_entry: The target agent's directory entry, if found.

        Returns:
            A ROAR response message.
        """
        if target_entry is not None:
            target_card = target_entry.agent_card
            response_payload: Dict[str, Any] = {
                "status": "routed",
                "target_did": target_card.identity.did,
                "target_name": target_card.identity.display_name,
                "original_intent": roar_msg.intent.value,
                "original_payload": roar_msg.payload,
            }
            to_identity = target_card.identity
        else:
            response_payload = {
                "status": "no_route",
                "detail": "Target agent not found in directory",
                "original_intent": roar_msg.intent.value,
            }
            to_identity = roar_msg.from_identity

        return ROARMessage(
            **cast(Dict[str, Any], {
                "from": to_identity,
                "to": roar_msg.from_identity,
            }),
            intent=MessageIntent.RESPOND,
            payload=response_payload,
            context={"protocol": "roar", "bridge": True},
        )

    def _translate_from_roar(
        self,
        roar_msg: ROARMessage,
        target_protocol: str,
        original_request: dict,
    ) -> dict:
        """Translate a ROAR response to the target protocol format.

        Args:
            roar_msg: The ROAR response message.
            target_protocol: The target agent's preferred protocol.
            original_request: The original incoming request (for JSON-RPC id).

        Returns:
            A response dict in the target protocol format.
        """
        if target_protocol == "roar":
            return self._roar_response(roar_msg)
        elif target_protocol == "mcp":
            return self._mcp_response(roar_msg, original_request)
        elif target_protocol == "a2a":
            return self._a2a_response(roar_msg, original_request)
        elif target_protocol == "acp":
            return self._acp_response(roar_msg)
        else:
            # Default to ROAR format
            return self._roar_response(roar_msg)

    def _roar_response(self, msg: ROARMessage) -> dict:
        """Format a ROAR native response."""
        return msg.model_dump(by_alias=True)

    def _mcp_response(self, msg: ROARMessage, original_request: dict) -> dict:
        """Format an MCP JSON-RPC response."""
        mcp_data = MCPAdapter.roar_to_mcp(msg)
        return {
            "jsonrpc": "2.0",
            "id": original_request.get("id", 1),
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": str(msg.payload.get("status", "")),
                    }
                ],
                **mcp_data,
            },
        }

    def _a2a_response(self, msg: ROARMessage, original_request: dict) -> dict:
        """Format an A2A task response."""
        a2a_data = A2AAdapter.roar_to_a2a(msg)
        return {
            "jsonrpc": "2.0",
            "id": original_request.get("id", 1),
            "result": {
                "id": a2a_data.get("task_id", msg.id),
                "status": {
                    "state": "completed" if msg.payload.get("status") == "routed" else "failed",
                    "message": msg.payload.get("detail", ""),
                },
                "artifacts": [],
                **a2a_data,
            },
        }

    def _acp_response(self, msg: ROARMessage) -> dict:
        """Format an ACP response."""
        if _ACP_AVAILABLE:
            return ACPAdapter.roar_to_acp_message(msg)

        # Fallback without ACPAdapter
        content = msg.payload.get("content") or msg.payload.get("status", "")
        return {
            "role": "assistant",
            "content": content if isinstance(content, str) else str(content),
        }
