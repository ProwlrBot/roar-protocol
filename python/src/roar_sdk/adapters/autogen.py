# -*- coding: utf-8 -*-
"""ROAR AutoGen Adapter — translate between Microsoft AutoGen messages and ROAR.

AutoGen uses dict-based messages with "role", "content", "name" fields,
plus optional "tool_calls" and "function_call" for tool invocations.

Mapping:
  role="user"      → ASK
  role="assistant"  → RESPOND
  role="system"     → NOTIFY
  role="function"   → UPDATE (tool result)
  tool_calls present → DELEGATE (requesting tool execution)

Usage::

    from roar_sdk.adapters.autogen import AutoGenAdapter

    roar_msg = AutoGenAdapter.autogen_to_roar(
        {"role": "user", "content": "Review this code"},
        from_agent=user_id, to_agent=agent_id,
    )
"""

from __future__ import annotations

from typing import Any, Dict, cast

from ..types import AgentIdentity, MessageIntent, ROARMessage


class AutoGenAdapter:
    """Translate between AutoGen message dicts and ROARMessages."""

    _ROLE_TO_INTENT = {
        "user": MessageIntent.ASK,
        "assistant": MessageIntent.RESPOND,
        "system": MessageIntent.NOTIFY,
        "function": MessageIntent.UPDATE,
        "tool": MessageIntent.UPDATE,
    }

    @staticmethod
    def autogen_to_roar(
        message: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
        session_id: str = "",
    ) -> ROARMessage:
        """Convert an AutoGen message dict to a ROARMessage.

        Args:
            message: AutoGen message with role, content, optional tool_calls.
            from_agent: Sender identity.
            to_agent: Recipient identity.
            session_id: Optional session tracking ID.
        """
        role = message.get("role", "user")
        content = message.get("content", "")

        # Tool calls override intent to DELEGATE
        tool_calls = message.get("tool_calls", [])
        if tool_calls:
            intent = MessageIntent.DELEGATE
        else:
            intent = AutoGenAdapter._ROLE_TO_INTENT.get(role, MessageIntent.ASK)

        payload: Dict[str, Any] = {"content": content}
        if tool_calls:
            payload["tool_calls"] = tool_calls
        if message.get("function_call"):
            payload["function_call"] = message["function_call"]
        if message.get("name"):
            payload["name"] = message["name"]

        context: Dict[str, Any] = {"protocol": "autogen"}
        if session_id:
            context["session_id"] = session_id

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=intent,
            payload=payload,
            context=context,
        )

    @staticmethod
    def roar_to_autogen(msg: ROARMessage) -> Dict[str, Any]:
        """Convert a ROARMessage to an AutoGen message dict."""
        intent_to_role = {
            MessageIntent.ASK: "user",
            MessageIntent.RESPOND: "assistant",
            MessageIntent.NOTIFY: "system",
            MessageIntent.UPDATE: "function",
            MessageIntent.DELEGATE: "assistant",
            MessageIntent.EXECUTE: "assistant",
            MessageIntent.DISCOVER: "system",
        }

        role = intent_to_role.get(msg.intent, "assistant")
        content = msg.payload.get("content", "")

        result: Dict[str, Any] = {"role": role, "content": content}

        if "tool_calls" in msg.payload:
            result["tool_calls"] = msg.payload["tool_calls"]
        if "function_call" in msg.payload:
            result["function_call"] = msg.payload["function_call"]
        if "name" in msg.payload:
            result["name"] = msg.payload["name"]

        return result
