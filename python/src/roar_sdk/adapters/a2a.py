# -*- coding: utf-8 -*-
"""ROAR A2A Adapter — translate between A2A (Agent-to-Agent) protocol and ROAR.

A2A (Google) is a JSON-RPC 2.0 protocol for agent-to-agent communication.
It defines tasks, messages, artifacts, and agent cards for inter-agent
delegation and status tracking.

A2A JSON-RPC methods:
  tasks/send                       → send a task to an agent
  tasks/get                        → get task status
  tasks/cancel                     → cancel a task
  agent/authenticatedExtendedCard  → get agent card

Mapping (A2A → ROAR):
  tasks/send   → ROARMessage(intent=DELEGATE, payload={task_id, message content})
  tasks/get    → ROARMessage(intent=ASK, payload={task_id, query: "status"})
  tasks/cancel → ROARMessage(intent=NOTIFY, payload={event: "task.cancel", task_id})
  A2A agent card → ROAR AgentCard

Mapping (ROAR → A2A):
  RESPOND → A2A task {id, status: "completed", artifacts: [...]}
  UPDATE  → A2A task {id, status: "working"}
  NOTIFY  → A2A task event
  AgentCard → A2A agent card {name, description, url, skills}

Usage::

    from roar_sdk.adapters.a2a import A2AAdapter
    from roar_sdk import AgentIdentity

    sender = AgentIdentity(display_name="orchestrator")
    receiver = AgentIdentity(display_name="worker-agent")

    # Translate an incoming A2A JSON-RPC message to a ROARMessage
    a2a_msg = {
        "jsonrpc": "2.0", "method": "tasks/send", "id": 1,
        "params": {"id": "task-1", "message": {"role": "user", "parts": [{"type": "text", "text": "Hello"}]}}
    }
    roar_msg = A2AAdapter.a2a_to_roar(a2a_msg, from_agent=sender, to_agent=receiver)

    # Translate a ROARMessage back to an A2A task response
    a2a_task = A2AAdapter.roar_to_a2a_task(roar_msg, task_id="task-1")
"""

from __future__ import annotations

from typing import Any, Dict, List, cast

from ..types import AgentCard, AgentIdentity, MessageIntent, ROARMessage


class A2AAdapter:
    """Translate between A2A JSON-RPC messages and ROAR messages."""

    # ── A2A → ROAR ──────────────────────────────────────────────────────────

    @staticmethod
    def a2a_to_roar(
        a2a_message: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
    ) -> ROARMessage:
        """Translate an A2A JSON-RPC request to a ROARMessage.

        Dispatches based on the JSON-RPC ``method`` field:
          - ``tasks/send``   → DELEGATE
          - ``tasks/get``    → ASK
          - ``tasks/cancel`` → NOTIFY

        For bare task envelopes (no ``jsonrpc`` field), delegates to DELEGATE.

        Args:
            a2a_message: The raw A2A JSON-RPC dict.
            from_agent: The sending agent identity.
            to_agent: The receiving agent identity.

        Returns:
            A ROARMessage representing the A2A request.

        Raises:
            ValueError: If the A2A method is not recognised.
        """
        method = a2a_message.get("method", "")
        params = a2a_message.get("params", {})

        # Bare task envelope (no jsonrpc wrapper)
        if not method and "id" in a2a_message and "status" in a2a_message:
            return A2AAdapter._task_envelope_to_roar(a2a_message, from_agent, to_agent)

        if method == "tasks/send":
            return A2AAdapter._tasks_send_to_roar(params, from_agent, to_agent)
        elif method == "tasks/get":
            return A2AAdapter._tasks_get_to_roar(params, from_agent, to_agent)
        elif method == "tasks/cancel":
            return A2AAdapter._tasks_cancel_to_roar(params, from_agent, to_agent)
        elif method == "agent/authenticatedExtendedCard":
            return A2AAdapter._agent_card_request_to_roar(params, from_agent, to_agent)
        else:
            raise ValueError(f"Unknown A2A method: {method!r}")

    @staticmethod
    def _tasks_send_to_roar(
        params: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
    ) -> ROARMessage:
        """Translate tasks/send params to a DELEGATE message."""
        task_id = params.get("id", "")
        message = params.get("message", {})

        # Extract text content from A2A parts
        content = A2AAdapter._extract_text_from_parts(message.get("parts", []))

        payload: Dict[str, Any] = {
            "task_id": task_id,
            "content": content,
        }

        # Preserve full message structure for round-tripping
        if message:
            payload["a2a_message"] = message

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.DELEGATE,
            payload=payload,
            context={"protocol": "a2a", "task_id": task_id},
        )

    @staticmethod
    def _tasks_get_to_roar(
        params: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
    ) -> ROARMessage:
        """Translate tasks/get params to an ASK message."""
        task_id = params.get("id", "")

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.ASK,
            payload={"task_id": task_id, "query": "status"},
            context={"protocol": "a2a", "task_id": task_id},
        )

    @staticmethod
    def _tasks_cancel_to_roar(
        params: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
    ) -> ROARMessage:
        """Translate tasks/cancel params to a NOTIFY message."""
        task_id = params.get("id", "")

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.NOTIFY,
            payload={"event": "task.cancel", "task_id": task_id},
            context={"protocol": "a2a", "task_id": task_id},
        )

    @staticmethod
    def _agent_card_request_to_roar(
        params: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
    ) -> ROARMessage:
        """Translate agent/authenticatedExtendedCard to a DISCOVER message."""
        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.DISCOVER,
            payload={"query": "agent_card"},
            context={"protocol": "a2a"},
        )

    @staticmethod
    def _task_envelope_to_roar(
        task: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
    ) -> ROARMessage:
        """Translate a bare A2A task envelope to a DELEGATE message."""
        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.DELEGATE,
            payload=task,
            context={"protocol": "a2a", "task_id": task.get("id", "")},
        )

    # ── ROAR → A2A ──────────────────────────────────────────────────────────

    @staticmethod
    def roar_to_a2a_task(msg: ROARMessage, task_id: str = "") -> Dict[str, Any]:
        """Translate a ROARMessage to an A2A task response dict.

        Maps ROAR intent to A2A task state:
          RESPOND → completed, with artifacts containing the response content
          UPDATE  → working, no artifacts yet
          NOTIFY  → submitted or failed depending on event
          *       → submitted

        Args:
            msg: The ROARMessage to translate.
            task_id: Override task ID (defaults to msg context or msg id).

        Returns:
            An A2A task dict.
        """
        tid = task_id or msg.context.get("task_id", "") or msg.id

        if msg.intent == MessageIntent.RESPOND:
            content = msg.payload.get("content", msg.payload.get("result", ""))
            if not isinstance(content, str):
                content = str(content)
            return {
                "id": tid,
                "status": {"state": "completed"},
                "artifacts": [
                    {
                        "parts": [{"type": "text", "text": content}],
                    }
                ],
            }

        elif msg.intent == MessageIntent.UPDATE:
            task: Dict[str, Any] = {
                "id": tid,
                "status": {"state": "working"},
            }
            # Include progress message if available
            content = msg.payload.get("content", "")
            if content:
                task["status"]["message"] = {
                    "role": "agent",
                    "parts": [{"type": "text", "text": content}],
                }
            return task

        elif msg.intent == MessageIntent.NOTIFY:
            event = msg.payload.get("event", "")
            if "fail" in event or "error" in event:
                return {
                    "id": tid,
                    "status": {
                        "state": "failed",
                        "message": {
                            "role": "agent",
                            "parts": [{"type": "text", "text": msg.payload.get("reason", event)}],
                        },
                    },
                }
            elif "cancel" in event:
                return {
                    "id": tid,
                    "status": {"state": "failed"},
                }
            else:
                return {
                    "id": tid,
                    "status": {"state": "submitted"},
                }

        elif msg.intent == MessageIntent.DELEGATE:
            return {
                "id": tid,
                "status": {"state": "submitted"},
            }

        else:
            return {
                "id": tid,
                "status": {"state": "submitted"},
            }

    @staticmethod
    def roar_to_a2a_jsonrpc_response(
        msg: ROARMessage,
        request_id: Any = 1,
        task_id: str = "",
    ) -> Dict[str, Any]:
        """Wrap a ROARMessage as a full A2A JSON-RPC 2.0 response.

        Args:
            msg: The ROARMessage to translate.
            request_id: The JSON-RPC request ID to echo back.
            task_id: Override task ID.

        Returns:
            A JSON-RPC 2.0 response dict with the task as the result.
        """
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": A2AAdapter.roar_to_a2a_task(msg, task_id=task_id),
        }

    # ── Agent Card conversion ───────────────────────────────────────────────

    @staticmethod
    def roar_to_a2a_agent_card(card: AgentCard) -> Dict[str, Any]:
        """Convert a ROAR AgentCard to an A2A agent card dict.

        Args:
            card: The ROAR AgentCard to convert.

        Returns:
            An A2A agent card dict with name, description, url, and skills.
        """
        skills: List[Dict[str, Any]] = []
        for i, skill_name in enumerate(card.skills):
            skills.append({
                "id": f"skill-{i}",
                "name": skill_name,
                "description": "",
            })

        # Also include declared_capabilities as skills
        for cap in card.declared_capabilities:
            skills.append({
                "id": f"cap-{cap.name}",
                "name": cap.name,
                "description": cap.description,
            })

        url = card.endpoints.get("http", card.endpoints.get("https", ""))

        return {
            "name": card.identity.display_name,
            "description": card.description,
            "url": url,
            "version": card.identity.version,
            "skills": skills,
        }

    @staticmethod
    def a2a_agent_card_to_roar(
        a2a_card: Dict[str, Any],
        endpoint: str = "",
    ) -> Dict[str, Any]:
        """Convert an A2A agent card dict to a ROAR AgentCard dict.

        Returns a dict suitable for constructing an AgentCard + AgentIdentity.

        Args:
            a2a_card: The A2A agent card dict.
            endpoint: Override endpoint URL.

        Returns:
            A dict with identity, description, skills, endpoints, etc.
        """
        name = a2a_card.get("name", "unknown-agent")
        description = a2a_card.get("description", "")
        url = endpoint or a2a_card.get("url", "")

        skills: List[str] = [
            s.get("name", "") for s in a2a_card.get("skills", []) if s.get("name")
        ]

        return {
            "identity": {
                "did": "",  # will be auto-generated
                "display_name": name,
                "agent_type": "agent",
                "capabilities": skills,
                "version": a2a_card.get("version", "1.0"),
                "public_key": None,
            },
            "description": description,
            "skills": skills,
            "channels": [],
            "endpoints": {"http": url},
            "declared_capabilities": [],
            "metadata": {
                "protocol": "a2a",
                "original": a2a_card,
            },
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_text_from_parts(parts: List[Dict[str, Any]]) -> str:
        """Extract concatenated text from A2A message parts.

        A2A parts format: [{"type": "text", "text": "..."}, ...]
        Only text parts are extracted; other types are skipped.
        """
        texts: List[str] = []
        for part in parts:
            if part.get("type") == "text" and "text" in part:
                texts.append(part["text"])
        return "\n".join(texts) if texts else ""
