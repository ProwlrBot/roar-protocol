# -*- coding: utf-8 -*-
"""ROAR LangGraph Adapter — translate between LangGraph state and ROAR messages.

LangGraph uses graph-based state machines with state dicts containing
a "messages" list, "next" node pointer, and arbitrary metadata.

Mapping:
  State transition      → UPDATE (progress notification)
  Final state (no next) → RESPOND (task complete)
  New graph invocation  → DELEGATE (start task)
  Human input needed    → ASK

Usage::

    from roar_sdk.adapters.langgraph import LangGraphAdapter

    roar_msg = LangGraphAdapter.langgraph_state_to_roar(
        {"messages": [...], "next": "reviewer"},
        from_agent=graph_id, to_agent=user_id,
    )
"""

from __future__ import annotations

from typing import Any, Dict, List, cast

from ..types import AgentIdentity, MessageIntent, ROARMessage


class LangGraphAdapter:
    """Translate between LangGraph state dicts and ROARMessages."""

    @staticmethod
    def langgraph_state_to_roar(
        state: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
        session_id: str = "",
    ) -> ROARMessage:
        """Convert a LangGraph state dict to a ROARMessage.

        LangGraph state format::

            {
                "messages": [{"role": "user", "content": "..."}],
                "next": "node_name" | None,
                "metadata": {...},
            }

        Intent mapping:
          - next is None/empty → RESPOND (graph complete)
          - next == "__interrupt__" → ASK (human input needed)
          - next is set → UPDATE (in-progress transition)
        """
        messages = state.get("messages", [])
        next_node = state.get("next")

        # Determine intent from graph state
        if next_node == "__interrupt__":
            intent = MessageIntent.ASK
        elif next_node is None or next_node == "" or next_node == "__end__":
            intent = MessageIntent.RESPOND
        else:
            intent = MessageIntent.UPDATE

        # Extract last message content
        content = ""
        if messages:
            last = messages[-1]
            if isinstance(last, dict):
                content = last.get("content", "")
            elif isinstance(last, str):
                content = last

        payload: Dict[str, Any] = {"content": content}
        if next_node:
            payload["next_node"] = next_node
        if state.get("metadata"):
            payload["graph_metadata"] = state["metadata"]
        payload["message_count"] = len(messages)

        context: Dict[str, Any] = {"protocol": "langgraph"}
        if session_id:
            context["session_id"] = session_id

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=intent,
            payload=payload,
            context=context,
        )

    @staticmethod
    def langgraph_invoke_to_roar(
        input_messages: List[Dict[str, Any]],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
        graph_name: str = "",
    ) -> ROARMessage:
        """Convert a LangGraph invocation to a DELEGATE ROARMessage."""
        content = ""
        if input_messages:
            last = input_messages[-1]
            content = last.get("content", "") if isinstance(last, dict) else str(last)

        payload: Dict[str, Any] = {
            "content": content,
            "messages": input_messages,
        }
        if graph_name:
            payload["graph"] = graph_name

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.DELEGATE,
            payload=payload,
            context={"protocol": "langgraph"},
        )

    @staticmethod
    def roar_to_langgraph_state(msg: ROARMessage) -> Dict[str, Any]:
        """Convert a ROARMessage to a LangGraph state dict."""
        state: Dict[str, Any] = {
            "messages": msg.payload.get("messages", [
                {"role": "assistant", "content": msg.payload.get("content", "")}
            ]),
        }

        if msg.intent == MessageIntent.RESPOND:
            state["next"] = None
        elif msg.intent == MessageIntent.ASK:
            state["next"] = "__interrupt__"
        else:
            state["next"] = msg.payload.get("next_node", "")

        if "graph_metadata" in msg.payload:
            state["metadata"] = msg.payload["graph_metadata"]

        return state
