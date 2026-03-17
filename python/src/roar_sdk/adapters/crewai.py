# -*- coding: utf-8 -*-
"""ROAR CrewAI Adapter — translate between CrewAI tasks and ROAR messages.

CrewAI uses role-based agent orchestration with tasks that have
description, expected_output, agent role, tools, and context.

Mapping:
  CrewAI task assignment → DELEGATE
  CrewAI task result     → RESPOND
  CrewAI task progress   → UPDATE
  CrewAI task delegation → DELEGATE (hierarchical)

Usage::

    from roar_sdk.adapters.crewai import CrewAIAdapter

    roar_msg = CrewAIAdapter.crewai_task_to_roar(
        {"description": "Review PR #42", "expected_output": "approval or rejection"},
        from_agent=manager_id, to_agent=reviewer_id,
    )
"""

from __future__ import annotations

from typing import Any, Dict, cast

from ..types import AgentIdentity, MessageIntent, ROARMessage


class CrewAIAdapter:
    """Translate between CrewAI task dicts and ROARMessages."""

    @staticmethod
    def crewai_task_to_roar(
        task: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
        session_id: str = "",
    ) -> ROARMessage:
        """Convert a CrewAI task dict to a DELEGATE ROARMessage.

        CrewAI task format::

            {
                "description": "Review the code changes",
                "expected_output": "A code review with approval/rejection",
                "agent": "code-reviewer",  # role name
                "tools": ["search", "read_file"],
                "context": ["previous task output"],
            }
        """
        payload: Dict[str, Any] = {
            "task": task.get("description", ""),
            "expected_output": task.get("expected_output", ""),
        }
        if task.get("tools"):
            payload["tools"] = task["tools"]
        if task.get("context"):
            payload["task_context"] = task["context"]
        if task.get("agent"):
            payload["assigned_role"] = task["agent"]

        context: Dict[str, Any] = {"protocol": "crewai"}
        if session_id:
            context["session_id"] = session_id

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.DELEGATE,
            payload=payload,
            context=context,
        )

    @staticmethod
    def crewai_result_to_roar(
        result: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
        in_reply_to: str = "",
    ) -> ROARMessage:
        """Convert a CrewAI task result to a RESPOND ROARMessage."""
        payload: Dict[str, Any] = {
            "result": result.get("output", result.get("result", "")),
        }
        if result.get("status"):
            payload["status"] = result["status"]

        context: Dict[str, Any] = {"protocol": "crewai"}
        if in_reply_to:
            context["in_reply_to"] = in_reply_to

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.RESPOND,
            payload=payload,
            context=context,
        )

    @staticmethod
    def roar_to_crewai_task(msg: ROARMessage) -> Dict[str, Any]:
        """Convert a DELEGATE ROARMessage to a CrewAI task dict."""
        return {
            "description": msg.payload.get("task", msg.payload.get("content", "")),
            "expected_output": msg.payload.get("expected_output", ""),
            "tools": msg.payload.get("tools", []),
            "context": msg.payload.get("task_context", []),
        }

    @staticmethod
    def roar_to_crewai_result(msg: ROARMessage) -> Dict[str, Any]:
        """Convert a RESPOND ROARMessage to a CrewAI result dict."""
        return {
            "output": msg.payload.get("result", msg.payload.get("content", "")),
            "status": msg.payload.get("status", "completed"),
            "agent": msg.from_identity.display_name,
        }
