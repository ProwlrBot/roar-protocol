# -*- coding: utf-8 -*-
"""ROAR Protocol — protocol adapters for backward compatibility.

Available adapters:
  MCPAdapter  — translate MCP tool calls ↔ ROARMessage (in roar_sdk.types)
  A2AAdapter  — translate A2A tasks ↔ ROARMessage (in roar_sdk.types)
  ACPAdapter  — translate ACP sessions ↔ ROARMessage (in roar_sdk.adapters.acp)
"""

from .acp import ACPAdapter

__all__ = ["ACPAdapter"]
