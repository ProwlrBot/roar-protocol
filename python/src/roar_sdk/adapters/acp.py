# -*- coding: utf-8 -*-
"""ROAR ACP Adapter — translate between ACP (Agent Communication Protocol) and ROAR.

ACP (IBM/BeeAI) is a session-based HTTP protocol for IDE-to-agent communication.
It defines sessions, messages, and responses but has no identity, signing, or
federation layer.

Mapping:
  ACP session start   → ROARMessage(intent=NOTIFY, payload={"event": "session.start"})
  ACP message         → ROARMessage(intent=ASK)    if awaiting human input
                      → ROARMessage(intent=UPDATE)  if reporting progress
  ACP response        → ROARMessage(intent=RESPOND)
  ACP session end     → ROARMessage(intent=NOTIFY, payload={"event": "session.end"})

ACP wire format (simplified):
  POST /sessions            → create session, returns session_id
  POST /sessions/{id}/runs  → send message, returns run_id + response stream
  GET  /sessions/{id}       → get session state

Usage::

    from roar_sdk.adapters import ACPAdapter
    from roar_sdk import AgentIdentity, MessageIntent

    ide = AgentIdentity(display_name="vscode", agent_type="ide")
    agent = AgentIdentity(display_name="my-agent")

    # Translate an incoming ACP message to a ROARMessage
    acp_msg = {"content": "Explain this function", "role": "user"}
    roar_msg = ACPAdapter.acp_to_roar(acp_msg, from_agent=ide, to_agent=agent)

    # Translate a ROARMessage back to ACP response format
    acp_response = ACPAdapter.roar_to_acp(roar_msg)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, cast

from ..types import AgentIdentity, MessageIntent, ROARMessage


class ACPAdapter:
    """Translate between ACP sessions/messages and ROAR messages."""

    # ── ACP → ROAR ──────────────────────────────────────────────────────────

    @staticmethod
    def acp_message_to_roar(
        acp_message: Dict[str, Any],
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
        session_id: str = "",
    ) -> ROARMessage:
        """Translate an ACP message dict to a ROARMessage.

        ACP message format::

            {
                "role": "user" | "assistant",
                "content": str | list,
                "attachments": [...]  # optional
            }

        The intent is derived from role:
          - "user" → ASK (user is requesting something from the agent)
          - "assistant" → RESPOND (agent is replying)
        """
        role = acp_message.get("role", "user")
        content = acp_message.get("content", "")
        attachments = acp_message.get("attachments", [])

        intent = MessageIntent.ASK if role == "user" else MessageIntent.RESPOND

        payload: Dict[str, Any] = {"content": content}
        if attachments:
            payload["attachments"] = attachments

        context: Dict[str, Any] = {"protocol": "acp"}
        if session_id:
            context["session_id"] = session_id

        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=intent,
            payload=payload,
            context=context,
        )

    @staticmethod
    def acp_session_event_to_roar(
        event: str,  # "start" | "end"
        from_agent: AgentIdentity,
        to_agent: AgentIdentity,
        session_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ROARMessage:
        """Translate an ACP session lifecycle event to a ROARMessage."""
        return ROARMessage(
            **cast(Dict[str, Any], {"from": from_agent, "to": to_agent}),
            intent=MessageIntent.NOTIFY,
            payload={"event": f"session.{event}", **(metadata or {})},
            context={"protocol": "acp", "session_id": session_id},
        )

    # ── ROAR → ACP ──────────────────────────────────────────────────────────

    @staticmethod
    def roar_to_acp_message(msg: ROARMessage) -> Dict[str, Any]:
        """Translate a ROARMessage to an ACP message dict.

        Maps intent to ACP role:
          RESPOND → "assistant"
          ASK     → "user" (agent asking human for input)
          UPDATE  → "assistant" with status metadata
          NOTIFY  → "assistant" with event metadata
          *       → "assistant"
        """
        intent_to_role = {
            MessageIntent.RESPOND: "assistant",
            MessageIntent.ASK: "user",
            MessageIntent.UPDATE: "assistant",
            MessageIntent.NOTIFY: "assistant",
        }
        role = intent_to_role.get(msg.intent, "assistant")

        # Prefer a "content" field, fall back to full payload as string
        content = msg.payload.get("content") or msg.payload.get("result") or msg.payload

        acp: Dict[str, Any] = {"role": role, "content": content}

        # Carry attachments through if present
        if "attachments" in msg.payload:
            acp["attachments"] = msg.payload["attachments"]

        return acp

    @staticmethod
    def roar_to_acp_run(msg: ROARMessage, run_id: str = "") -> Dict[str, Any]:
        """Translate a ROARMessage to an ACP run response (richer format)."""
        import time

        return {
            "run_id": run_id or msg.id,
            "session_id": msg.context.get("session_id", ""),
            "status": "completed" if msg.intent == MessageIntent.RESPOND else "in_progress",
            "output": ACPAdapter.roar_to_acp_message(msg),
            "metadata": {
                "roar_intent": msg.intent,
                "roar_message_id": msg.id,
                "from_did": msg.from_identity.did,
                "timestamp": msg.timestamp,
            },
            "created_at": time.time(),
        }

    # ── Agent Card ↔ ACP Agent ───────────────────────────────────────────────

    @staticmethod
    def well_known_agent_to_card(
        well_known: Dict[str, Any],
        endpoint: str = "",
    ) -> Dict[str, Any]:
        """Convert an A2A/ACP /.well-known/agent.json to a ROAR AgentCard dict.

        Returns a dict suitable for constructing an AgentCard + AgentIdentity.
        """
        name = well_known.get("name", "unknown-agent")
        description = well_known.get("description", "")
        skills: List[str] = [
            s.get("name", "") for s in well_known.get("skills", []) if s.get("name")
        ]

        return {
            "identity": {
                "did": "",  # will be auto-generated
                "display_name": name,
                "agent_type": "agent",
                "capabilities": skills,
                "version": well_known.get("version", "1.0"),
                "public_key": None,
            },
            "description": description,
            "skills": skills,
            "channels": well_known.get("supportedModes", []),
            "endpoints": {"http": endpoint or well_known.get("url", "")},
            "declared_capabilities": [],
            "metadata": {
                "protocol": "acp",
                "original": well_known,
            },
        }
