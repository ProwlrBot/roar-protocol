# -*- coding: utf-8 -*-
"""Protocol auto-detection — sniff incoming messages to identify their format.

Examines the structure of an incoming JSON message to determine whether
it's ROAR native, MCP (JSON-RPC 2.0), A2A, or ACP protocol format, then
routes to the appropriate adapter.

Usage::

    from roar_sdk.adapters.detect import detect_protocol, ProtocolType

    msg = json.loads(raw_body)
    protocol = detect_protocol(msg)

    if protocol == ProtocolType.ROAR:
        roar_msg = ROARMessage.model_validate(msg)
    elif protocol == ProtocolType.MCP:
        roar_msg = MCPAdapter.mcp_to_roar(...)
    elif protocol == ProtocolType.A2A:
        roar_msg = A2AAdapter.a2a_task_to_roar(...)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict


class ProtocolType(str, Enum):
    """Detected protocol type."""

    ROAR = "roar"
    MCP = "mcp"
    A2A = "a2a"
    ACP = "acp"
    AUTOGEN = "autogen"
    CREWAI = "crewai"
    LANGGRAPH = "langgraph"
    UNKNOWN = "unknown"


_MCP_METHOD_PREFIXES = (
    "tools/",
    "resources/",
    "prompts/",
    "completion/",
    "initialize",
    "notifications/",
)

_A2A_METHOD_PREFIXES = ("tasks/", "agent/")


def detect_protocol(message: Dict[str, Any]) -> ProtocolType:
    """Detect the protocol of an incoming message.

    Detection heuristics (in priority order):
    1. ROAR: Has "roar" version field and "intent" field
    2. ACP: Has "role" field and "content" field (ACP message body)
    3. MCP: JSON-RPC 2.0 with MCP method prefix
    4. A2A: JSON-RPC 2.0 with tasks/ or agent/ method prefix, or task envelope

    Args:
        message: The raw JSON message dict.

    Returns:
        The detected ProtocolType.
    """
    # ROAR native
    if "roar" in message and "intent" in message:
        return ProtocolType.ROAR

    # AutoGen: role+content with tool_calls, function_call, or function/tool role
    if "role" in message and "content" in message:
        if "tool_calls" in message or "function_call" in message:
            return ProtocolType.AUTOGEN
        if message.get("role") in ("function", "tool") and "name" in message:
            return ProtocolType.AUTOGEN

    # ACP message (session-based, role/content structure — after AutoGen check)
    if "role" in message and "content" in message:
        return ProtocolType.ACP

    # JSON-RPC based protocols
    if message.get("jsonrpc") == "2.0":
        method = message.get("method", "")

        if any(method.startswith(p) for p in _A2A_METHOD_PREFIXES):
            return ProtocolType.A2A

        if any(method.startswith(p) for p in _MCP_METHOD_PREFIXES):
            return ProtocolType.MCP

        # Infer from result structure
        result = message.get("result", {})
        if isinstance(result, dict):
            if "status" in result and "id" in result:
                return ProtocolType.A2A
            if "tools" in result or "resources" in result:
                return ProtocolType.MCP

    # A2A task envelope (no jsonrpc wrapper)
    if "status" in message and "id" in message and "artifacts" in message:
        return ProtocolType.A2A

    # CrewAI: task with "description" + "expected_output"
    if "description" in message and "expected_output" in message:
        return ProtocolType.CREWAI

    # LangGraph: state with "messages" list + "next" node
    if "messages" in message and isinstance(message.get("messages"), list):
        if "next" in message:
            return ProtocolType.LANGGRAPH

    return ProtocolType.UNKNOWN
