# -*- coding: utf-8 -*-
"""ROAR Protocol — protocol adapters for cross-framework interoperability.

Available adapters:
  ACPAdapter      — ACP sessions ↔ ROARMessage
  AutoGenAdapter  — Microsoft AutoGen messages ↔ ROARMessage
  CrewAIAdapter   — CrewAI tasks ↔ ROARMessage
  LangGraphAdapter — LangGraph state ↔ ROARMessage
  MCPAdapter      — MCP tool calls ↔ ROARMessage (in roar_sdk.types)
  A2AAdapter      — A2A tasks ↔ ROARMessage (in roar_sdk.types)
"""

from .acp import ACPAdapter
from .autogen import AutoGenAdapter
from .crewai import CrewAIAdapter
from .langgraph import LangGraphAdapter

__all__ = ["ACPAdapter", "AutoGenAdapter", "CrewAIAdapter", "LangGraphAdapter"]
