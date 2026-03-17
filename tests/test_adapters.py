# -*- coding: utf-8 -*-
"""Tests for ROAR protocol adapters and auto-detection."""

import pytest

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.adapters.detect import ProtocolType, detect_protocol
from roar_sdk.adapters.acp import ACPAdapter


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def agent_a():
    return AgentIdentity(display_name="agent-a", capabilities=["test"])

@pytest.fixture
def agent_b():
    return AgentIdentity(display_name="agent-b", capabilities=["test"])


# ── Protocol Detection ───────────────────────────────────────────────────────

class TestDetectProtocol:
    def test_roar_native(self):
        msg = {"roar": "1.0", "intent": "execute", "from": {}, "to": {}}
        assert detect_protocol(msg) == ProtocolType.ROAR

    def test_mcp_tools_list(self):
        msg = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_mcp_tools_call(self):
        msg = {"jsonrpc": "2.0", "method": "tools/call", "id": 2, "params": {}}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_mcp_resources(self):
        msg = {"jsonrpc": "2.0", "method": "resources/read", "id": 3}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_mcp_initialize(self):
        msg = {"jsonrpc": "2.0", "method": "initialize", "id": 1}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_mcp_result_with_tools(self):
        msg = {"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_a2a_tasks_send(self):
        msg = {"jsonrpc": "2.0", "method": "tasks/send", "id": 1, "params": {}}
        assert detect_protocol(msg) == ProtocolType.A2A

    def test_a2a_agent_method(self):
        msg = {"jsonrpc": "2.0", "method": "agent/info", "id": 1}
        assert detect_protocol(msg) == ProtocolType.A2A

    def test_a2a_result_with_status(self):
        msg = {"jsonrpc": "2.0", "result": {"status": "completed", "id": "task-1"}, "id": 1}
        assert detect_protocol(msg) == ProtocolType.A2A

    def test_a2a_task_envelope(self):
        msg = {"id": "task-1", "status": "completed", "artifacts": []}
        assert detect_protocol(msg) == ProtocolType.A2A

    def test_acp_message(self):
        msg = {"role": "user", "content": "Hello agent"}
        assert detect_protocol(msg) == ProtocolType.ACP

    def test_acp_assistant_message(self):
        msg = {"role": "assistant", "content": "I can help with that"}
        assert detect_protocol(msg) == ProtocolType.ACP

    def test_unknown_empty(self):
        assert detect_protocol({}) == ProtocolType.UNKNOWN

    def test_unknown_random_keys(self):
        msg = {"foo": "bar", "baz": 42}
        assert detect_protocol(msg) == ProtocolType.UNKNOWN

    def test_unknown_jsonrpc_no_known_method(self):
        msg = {"jsonrpc": "2.0", "method": "custom/something", "id": 1}
        assert detect_protocol(msg) == ProtocolType.UNKNOWN

    def test_roar_takes_priority_over_acp(self):
        """If a message has both ROAR and ACP fields, ROAR wins."""
        msg = {"roar": "1.0", "intent": "execute", "role": "user", "content": "test"}
        assert detect_protocol(msg) == ProtocolType.ROAR


# ── ACP Adapter ──────────────────────────────────────────────────────────────

class TestACPAdapter:
    def test_user_message_to_roar(self, agent_a, agent_b):
        acp = {"role": "user", "content": "Explain this function"}
        msg = ACPAdapter.acp_message_to_roar(acp, from_agent=agent_a, to_agent=agent_b)
        assert msg.intent == MessageIntent.ASK
        assert msg.payload["content"] == "Explain this function"
        assert msg.context.get("protocol") == "acp"

    def test_assistant_message_to_roar(self, agent_a, agent_b):
        acp = {"role": "assistant", "content": "Here is the explanation"}
        msg = ACPAdapter.acp_message_to_roar(acp, from_agent=agent_a, to_agent=agent_b)
        assert msg.intent == MessageIntent.RESPOND
        assert msg.payload["content"] == "Here is the explanation"

    def test_message_with_session_id(self, agent_a, agent_b):
        acp = {"role": "user", "content": "test"}
        msg = ACPAdapter.acp_message_to_roar(acp, agent_a, agent_b, session_id="sess-1")
        assert msg.context["session_id"] == "sess-1"

    def test_message_with_attachments(self, agent_a, agent_b):
        acp = {"role": "user", "content": "Review this", "attachments": [{"file": "main.py"}]}
        msg = ACPAdapter.acp_message_to_roar(acp, agent_a, agent_b)
        assert msg.payload["attachments"] == [{"file": "main.py"}]

    def test_session_start_event(self, agent_a, agent_b):
        msg = ACPAdapter.acp_session_event_to_roar("start", agent_a, agent_b, session_id="s1")
        assert msg.intent == MessageIntent.NOTIFY
        assert msg.payload["event"] == "session.start"
        assert msg.context["session_id"] == "s1"

    def test_session_end_event(self, agent_a, agent_b):
        msg = ACPAdapter.acp_session_event_to_roar("end", agent_a, agent_b)
        assert msg.intent == MessageIntent.NOTIFY
        assert msg.payload["event"] == "session.end"

    def test_roar_respond_to_acp(self, agent_a, agent_b):
        msg = ROARMessage(
            **{"from": agent_a, "to": agent_b},
            intent=MessageIntent.RESPOND,
            payload={"content": "Done!"},
        )
        acp = ACPAdapter.roar_to_acp_message(msg)
        assert acp["role"] == "assistant"
        assert acp["content"] == "Done!"

    def test_roar_ask_to_acp(self, agent_a, agent_b):
        msg = ROARMessage(
            **{"from": agent_a, "to": agent_b},
            intent=MessageIntent.ASK,
            payload={"content": "What next?"},
        )
        acp = ACPAdapter.roar_to_acp_message(msg)
        assert acp["role"] == "user"
        assert acp["content"] == "What next?"

    def test_roar_to_acp_run(self, agent_a, agent_b):
        msg = ROARMessage(
            **{"from": agent_a, "to": agent_b},
            intent=MessageIntent.RESPOND,
            payload={"content": "Result here"},
            context={"session_id": "s1"},
        )
        run = ACPAdapter.roar_to_acp_run(msg, run_id="run-123")
        assert run["run_id"] == "run-123"
        assert run["session_id"] == "s1"
        assert run["status"] == "completed"
        assert run["output"]["role"] == "assistant"
        assert run["metadata"]["roar_intent"] == MessageIntent.RESPOND

    def test_round_trip_user_message(self, agent_a, agent_b):
        """ACP user message → ROAR → ACP should preserve content."""
        original = {"role": "user", "content": "Please help me debug this"}
        roar_msg = ACPAdapter.acp_message_to_roar(original, agent_a, agent_b)
        back = ACPAdapter.roar_to_acp_message(roar_msg)
        assert back["content"] == original["content"]
        assert back["role"] == original["role"]

    def test_round_trip_with_attachments(self, agent_a, agent_b):
        original = {"role": "user", "content": "Review", "attachments": [{"f": "x.py"}]}
        roar_msg = ACPAdapter.acp_message_to_roar(original, agent_a, agent_b)
        back = ACPAdapter.roar_to_acp_message(roar_msg)
        assert back["content"] == "Review"
        assert back["attachments"] == [{"f": "x.py"}]

    def test_well_known_to_card(self):
        wk = {
            "name": "test-agent",
            "description": "A test agent",
            "version": "2.0",
            "skills": [{"name": "analyze"}, {"name": "report"}],
            "supportedModes": ["http", "websocket"],
            "url": "https://agent.example.com",
        }
        card = ACPAdapter.well_known_agent_to_card(wk)
        assert card["identity"]["display_name"] == "test-agent"
        assert card["description"] == "A test agent"
        assert "analyze" in card["skills"]
        assert "report" in card["skills"]
        assert card["endpoints"]["http"] == "https://agent.example.com"
        assert card["channels"] == ["http", "websocket"]


# ── MCP Adapter ──────────────────────────────────────────────────────────────

class TestMCPAdapter:
    def test_mcp_adapter_exists(self):
        """Check if MCPAdapter is available in types."""
        try:
            from roar_sdk.types import MCPAdapter
            assert hasattr(MCPAdapter, "mcp_to_roar") or hasattr(MCPAdapter, "mcp_call_to_roar")
        except ImportError:
            pytest.skip("MCPAdapter not available in types")


# ── A2A Adapter ──────────────────────────────────────────────────────────────

class TestA2AAdapter:
    def test_a2a_adapter_exists(self):
        """Check if A2AAdapter is available in types."""
        try:
            from roar_sdk.types import A2AAdapter
            assert hasattr(A2AAdapter, "a2a_to_roar") or hasattr(A2AAdapter, "a2a_task_to_roar")
        except ImportError:
            pytest.skip("A2AAdapter not available in types")
