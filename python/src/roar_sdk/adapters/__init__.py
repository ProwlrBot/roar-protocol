# -*- coding: utf-8 -*-
"""ROAR Protocol — protocol adapters for cross-framework interoperability.

Available adapters:
  ACPAdapter       — ACP sessions ↔ ROARMessage
  AutoGenAdapter   — Microsoft AutoGen messages ↔ ROARMessage
  CrewAIAdapter    — CrewAI tasks ↔ ROARMessage
  LangGraphAdapter — LangGraph state ↔ ROARMessage
  MCPAdapter       — MCP JSON-RPC 2.0 ↔ ROARMessage
  A2AAdapter       — A2A JSON-RPC tasks ↔ ROARMessage
"""

from .a2a import A2AAdapter
from .acp import ACPAdapter
from .autogen import AutoGenAdapter
from .crewai import CrewAIAdapter
from .langgraph import LangGraphAdapter
from .mcp import MCPAdapter

__all__ = ["A2AAdapter", "ACPAdapter", "AutoGenAdapter", "CrewAIAdapter", "LangGraphAdapter", "MCPAdapter"]
