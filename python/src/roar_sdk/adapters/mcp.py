# -*- coding: utf-8 -*-
"""ROAR MCP Adapter — translate between MCP (JSON-RPC 2.0) and ROAR messages.

MCP (Model Context Protocol) uses JSON-RPC 2.0 for communication between
hosts and servers. It defines tools, resources, and prompts as core primitives.

Mapping (MCP → ROAR):
  tools/call {name, arguments}       → ROARMessage(intent=EXECUTE, payload={tool, arguments})
  tools/list                         → ROARMessage(intent=DISCOVER, payload={type: "tools"})
  resources/read {uri}               → ROARMessage(intent=EXECUTE, payload={resource: uri})
  prompts/get {name, arguments}      → ROARMessage(intent=ASK, payload={prompt, arguments})
  initialize                         → ROARMessage(intent=NOTIFY, payload={event: "initialize"})
  notifications/*                    → ROARMessage(intent=NOTIFY)

Mapping (ROAR → MCP):
  RESPOND with tool result           → JSON-RPC result with content array
  RESPOND with tool list             → JSON-RPC result with tools array
  AgentCard                          → MCP tool definition (name/description/inputSchema)

Usage::

    from roar_sdk.adapters.mcp import MCPAdapter
    from roar_sdk import AgentIdentity

    host = AgentIdentity(display_name="claude-desktop", agent_type="ide")
    server = AgentIdentity(display_name="file-server", agent_type="tool")

    # Translate an incoming MCP request to a ROARMessage
    mcp_req = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": "read_file", "arguments": {"path": "/tmp/x.txt"}}
    }
    roar_msg = MCPAdapter.mcp_to_roar(mcp_req, from_agent=host, to_agent=server)

    # Translate a ROARMessage back to an MCP JSON-RPC response
    mcp_response = MCPAdapter.roar_to_mcp_result(roar_msg, request_id=1)
"""

from __future__ import annotations

from typing import Any, Dict, List, cast

from ..types import AgentCapability, AgentCard, AgentIdentity, MessageIntent, ROARMessage


class MCPAdapter:
    """Translate between MCP JSON-RPC 2.0 messages and ROAR messages."""

    # ── MCP → ROAR ──────────────────────────────────────────────────────────

    @staticmethod
    def mcp_to_roar(
        mcp_message: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
    ) -> ROARMessage:
        """Translate an MCP JSON-RPC 2.0 request to a ROARMessage.

        Supports:
          - tools/call      → EXECUTE with tool name and arguments
          - tools/list      → DISCOVER with type "tools"
          - resources/read  → EXECUTE with resource URI
          - prompts/get     → ASK with prompt name and arguments
          - initialize      → NOTIFY with event "initialize"
          - notifications/* → NOTIFY with event from method name

        Args:
            mcp_message: The raw MCP JSON-RPC 2.0 message dict.
            from_agent: The agent identity of the sender (MCP host/client).
            to_agent: The agent identity of the receiver (MCP server).

        Returns:
            A ROARMessage representing the MCP request.
        """
        method = mcp_message.get("method", "")
        params = mcp_message.get("params") or {}
        request_id = mcp_message.get("id")

        intent: MessageIntent
        payload: Dict[str, Any]

        if method == "tools/call":
            intent = MessageIntent.EXECUTE
            payload = {
                "tool": params.get("name", ""),
                "arguments": params.get("arguments", {}),
            }

        elif method == "tools/list":
            intent = MessageIntent.DISCOVER
            payload = {"type": "tools"}

        elif method == "resources/read":
            intent = MessageIntent.EXECUTE
            payload = {"resource": params.get("uri", "")}

        elif method == "prompts/get":
            intent = MessageIntent.ASK
            payload = {
                "prompt": params.get("name", ""),
                "arguments": params.get("arguments", {}),
            }

        elif method == "initialize":
            intent = MessageIntent.NOTIFY
            payload = {
                "event": "initialize",
                **{k: v for k, v in params.items() if k != "event"},
            }

        elif method.startswith("notifications/"):
            intent = MessageIntent.NOTIFY
            event_name = method.replace("notifications/", "", 1)
            payload = {"event": event_name, **params}

        else:
            # Unknown MCP method — map to EXECUTE as a best-effort fallback
            intent = MessageIntent.EXECUTE
            payload = {"method": method, **params}

        context: Dict[str, Any] = {"protocol": "mcp", "method": method}
        if request_id is not None:
            context["request_id"] = request_id

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=intent,
            payload=payload,
            context=context,
        )

    # ── ROAR → MCP ──────────────────────────────────────────────────────────

    @staticmethod
    def roar_to_mcp_result(
        msg: ROARMessage,
        request_id: Any = None,
    ) -> Dict[str, Any]:
        """Translate a ROARMessage to an MCP JSON-RPC 2.0 response.

        Handles two main cases:
          - Tool list response (DISCOVER/RESPOND with "tools" in payload)
          - Tool/resource result response (RESPOND/EXECUTE result)

        Args:
            msg: The ROARMessage to translate.
            request_id: The JSON-RPC request id to echo back. If None, uses
                the request_id from the message context.

        Returns:
            A JSON-RPC 2.0 response dict.
        """
        rid = request_id if request_id is not None else msg.context.get("request_id")

        # Tool list response
        if "tools" in msg.payload:
            return {
                "jsonrpc": "2.0",
                "result": {"tools": msg.payload["tools"]},
                "id": rid,
            }

        # Tool/resource result — wrap in MCP content array
        result_text = ""
        if "result" in msg.payload:
            result_value = msg.payload["result"]
            result_text = result_value if isinstance(result_value, str) else str(result_value)
        elif "content" in msg.payload:
            content_value = msg.payload["content"]
            # If content is already an MCP content array, pass through
            if isinstance(content_value, list):
                return {
                    "jsonrpc": "2.0",
                    "result": {"content": content_value},
                    "id": rid,
                }
            result_text = content_value if isinstance(content_value, str) else str(content_value)
        else:
            # Serialize the full payload as the result text
            import json
            result_text = json.dumps(msg.payload)

        return {
            "jsonrpc": "2.0",
            "result": {
                "content": [{"type": "text", "text": result_text}],
            },
            "id": rid,
        }

    # ── Agent Card ↔ MCP Tool ───────────────────────────────────────────────

    @staticmethod
    def agent_card_to_mcp_tool(card: AgentCard) -> Dict[str, Any]:
        """Convert a ROAR AgentCard to an MCP tool definition.

        Maps the card's identity and first declared capability to an MCP tool
        with name, description, and inputSchema.

        Args:
            card: The AgentCard to convert.

        Returns:
            An MCP tool definition dict with name, description, and inputSchema.
        """
        # Use the first declared capability's input schema if available
        input_schema: Dict[str, Any] = {"type": "object", "properties": {}}
        if card.declared_capabilities:
            cap = card.declared_capabilities[0]
            if cap.input_schema:
                input_schema = cap.input_schema

        return {
            "name": card.identity.display_name,
            "description": card.description or f"Agent: {card.identity.display_name}",
            "inputSchema": input_schema,
        }

    @staticmethod
    def mcp_tool_to_agent_card(tool: Dict[str, Any]) -> AgentCard:
        """Convert an MCP tool definition to a ROAR AgentCard.

        Args:
            tool: An MCP tool definition dict with name, description,
                and optionally inputSchema.

        Returns:
            An AgentCard representing the MCP tool.
        """
        name = tool.get("name", "unknown-tool")
        description = tool.get("description", "")
        input_schema = tool.get("inputSchema", {})

        identity = AgentIdentity(
            display_name=name,
            agent_type="tool",
            capabilities=[name],
        )

        capabilities: List[AgentCapability] = []
        if input_schema:
            capabilities.append(
                AgentCapability(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                )
            )

        return AgentCard(
            identity=identity,
            description=description,
            skills=[name],
            declared_capabilities=capabilities,
            metadata={"protocol": "mcp"},
        )
