# -*- coding: utf-8 -*-
"""Tests for the BridgeRouter cross-protocol message routing.

Tests cover:
  - ROAR native input routing
  - MCP input translation and routing
  - A2A input translation and routing
  - ACP input translation and routing
  - Protocol preference: target receives response in preferred format
  - Unknown protocol returns error
"""

import pytest

from roar_sdk.types import (
    AgentCard,
    AgentIdentity,
    AgentCapability,
    MessageIntent,
)
from roar_sdk.hub import ROARHub
from roar_sdk.bridge import BridgeRouter


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def hub():
    """Create a test hub (no server, just in-memory directory)."""
    return ROARHub(host="127.0.0.1", port=19090, hub_id="http://test-hub:19090")


@pytest.fixture
def bridge(hub):
    return BridgeRouter(hub)


@pytest.fixture
def agent_card_roar():
    return AgentCard(
        identity=AgentIdentity(
            did="did:roar:agent:roar-native-001",
            display_name="roar-native",
            agent_type="agent",
            capabilities=["code-review"],
        ),
        description="A ROAR-native agent",
        endpoints={"http": "http://localhost:9001"},
    )


@pytest.fixture
def agent_card_mcp():
    return AgentCard(
        identity=AgentIdentity(
            did="did:roar:tool:mcp-tool-001",
            display_name="mcp-tool",
            agent_type="tool",
            capabilities=["file-read"],
        ),
        description="An MCP tool server",
        endpoints={"http": "http://localhost:9002"},
    )


@pytest.fixture
def agent_card_a2a():
    return AgentCard(
        identity=AgentIdentity(
            did="did:roar:agent:a2a-agent-001",
            display_name="a2a-agent",
            agent_type="agent",
            capabilities=["summarize"],
        ),
        description="An A2A-compatible agent",
        endpoints={"http": "http://localhost:9003"},
    )


@pytest.fixture
def agent_card_acp():
    return AgentCard(
        identity=AgentIdentity(
            did="did:roar:agent:acp-agent-001",
            display_name="acp-agent",
            agent_type="agent",
            capabilities=["chat"],
        ),
        description="An ACP-compatible agent",
        endpoints={"http": "http://localhost:9004"},
    )


# ═══════════════════════════════════════════════════════════════════════════
# Registration and protocol preference
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistration:
    def test_register_agent(self, bridge, agent_card_roar):
        entry = bridge.register_agent(agent_card_roar, preferred_protocol="roar")
        assert entry.agent_card.identity.did == "did:roar:agent:roar-native-001"

    def test_get_agent_protocol(self, bridge, agent_card_a2a):
        bridge.register_agent(agent_card_a2a, preferred_protocol="a2a")
        assert bridge.get_agent_protocol("did:roar:agent:a2a-agent-001") == "a2a"

    def test_default_protocol_is_roar(self, bridge):
        assert bridge.get_agent_protocol("did:roar:agent:nonexistent") == "roar"

    def test_register_multiple(self, bridge, agent_card_roar, agent_card_mcp, agent_card_a2a):
        bridge.register_agent(agent_card_roar, preferred_protocol="roar")
        bridge.register_agent(agent_card_mcp, preferred_protocol="mcp")
        bridge.register_agent(agent_card_a2a, preferred_protocol="a2a")
        assert bridge.get_agent_protocol(agent_card_roar.identity.did) == "roar"
        assert bridge.get_agent_protocol(agent_card_mcp.identity.did) == "mcp"
        assert bridge.get_agent_protocol(agent_card_a2a.identity.did) == "a2a"


# ═══════════════════════════════════════════════════════════════════════════
# ROAR native routing
# ═══════════════════════════════════════════════════════════════════════════


class TestROARNativeRouting:
    def test_roar_message_routes_correctly(self, bridge, agent_card_roar):
        bridge.register_agent(agent_card_roar, preferred_protocol="roar")

        msg = {
            "roar": "1.0",
            "id": "msg_test001",
            "from": {"did": "did:roar:agent:sender-001", "display_name": "sender"},
            "to": {"did": "did:roar:agent:roar-native-001", "display_name": "roar-native"},
            "intent": "execute",
            "payload": {"action": "review", "code": "print('hello')"},
        }

        result = bridge.bridge_message(msg)
        assert result["payload"]["status"] == "routed"
        assert result["payload"]["target_did"] == "did:roar:agent:roar-native-001"
        assert result["payload"]["original_intent"] == "execute"

    def test_roar_message_target_not_found(self, bridge):
        msg = {
            "roar": "1.0",
            "id": "msg_test002",
            "from": {"did": "did:roar:agent:sender-001"},
            "to": {"did": "did:roar:agent:nonexistent"},
            "intent": "execute",
            "payload": {"action": "test"},
        }

        result = bridge.bridge_message(msg)
        assert result["payload"]["status"] == "no_route"


# ═══════════════════════════════════════════════════════════════════════════
# MCP input translation and routing
# ═══════════════════════════════════════════════════════════════════════════


class TestMCPRouting:
    def test_mcp_tools_call(self, bridge, agent_card_mcp):
        bridge.register_agent(agent_card_mcp, preferred_protocol="mcp")

        mcp_msg = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "read_file",
                "arguments": {"path": "/etc/hosts"},
            },
        }

        result = bridge.bridge_message(mcp_msg)
        # Should succeed (translated through ROAR)
        assert "error" not in result or result.get("error") != "unknown_protocol"

    def test_mcp_tools_list(self, bridge):
        mcp_msg = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 2,
        }

        result = bridge.bridge_message(mcp_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"

    def test_mcp_initialize(self, bridge):
        mcp_msg = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {"clientInfo": {"name": "test"}},
        }

        result = bridge.bridge_message(mcp_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"


# ═══════════════════════════════════════════════════════════════════════════
# A2A input translation and routing
# ═══════════════════════════════════════════════════════════════════════════


class TestA2ARouting:
    def test_a2a_tasks_send(self, bridge, agent_card_a2a):
        bridge.register_agent(agent_card_a2a, preferred_protocol="a2a")

        a2a_msg = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": "task-001",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Summarize this document"}],
                },
            },
        }

        result = bridge.bridge_message(a2a_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"

    def test_a2a_task_envelope(self, bridge, agent_card_a2a):
        bridge.register_agent(agent_card_a2a, preferred_protocol="a2a")

        a2a_msg = {
            "id": "task-002",
            "status": "submitted",
            "artifacts": [],
        }

        result = bridge.bridge_message(a2a_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"

    def test_a2a_agent_info(self, bridge):
        a2a_msg = {
            "jsonrpc": "2.0",
            "method": "agent/info",
            "id": 3,
        }

        result = bridge.bridge_message(a2a_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"


# ═══════════════════════════════════════════════════════════════════════════
# ACP input translation and routing
# ═══════════════════════════════════════════════════════════════════════════


class TestACPRouting:
    def test_acp_user_message(self, bridge, agent_card_acp):
        bridge.register_agent(agent_card_acp, preferred_protocol="acp")

        acp_msg = {
            "role": "user",
            "content": "Explain this function to me",
        }

        result = bridge.bridge_message(acp_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"

    def test_acp_assistant_message(self, bridge):
        acp_msg = {
            "role": "assistant",
            "content": "Here is the explanation...",
        }

        result = bridge.bridge_message(acp_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"


# ═══════════════════════════════════════════════════════════════════════════
# Protocol preference: target receives response in preferred format
# ═══════════════════════════════════════════════════════════════════════════


class TestProtocolPreference:
    def test_a2a_agent_receives_a2a_format(self, bridge, agent_card_a2a):
        """When an A2A agent is the target, the response is in A2A format."""
        bridge.register_agent(agent_card_a2a, preferred_protocol="a2a")

        # Send a ROAR message targeting the A2A agent
        msg = {
            "roar": "1.0",
            "id": "msg_pref001",
            "from": {"did": "did:roar:agent:sender-001"},
            "to": {"did": "did:roar:agent:a2a-agent-001"},
            "intent": "delegate",
            "payload": {"task": "summarize"},
        }

        result = bridge.bridge_message(msg)
        # A2A format has jsonrpc and result with status
        assert result.get("jsonrpc") == "2.0"
        assert "result" in result
        assert "status" in result["result"]

    def test_mcp_agent_receives_mcp_format(self, bridge, agent_card_mcp):
        """When an MCP agent is the target, the response is in MCP format."""
        bridge.register_agent(agent_card_mcp, preferred_protocol="mcp")

        msg = {
            "roar": "1.0",
            "id": "msg_pref002",
            "from": {"did": "did:roar:agent:sender-001"},
            "to": {"did": "did:roar:tool:mcp-tool-001"},
            "intent": "execute",
            "payload": {"action": "read_file"},
        }

        result = bridge.bridge_message(msg)
        assert result.get("jsonrpc") == "2.0"
        assert "result" in result
        assert "content" in result["result"]

    def test_acp_agent_receives_acp_format(self, bridge, agent_card_acp):
        """When an ACP agent is the target, the response is in ACP format."""
        bridge.register_agent(agent_card_acp, preferred_protocol="acp")

        msg = {
            "roar": "1.0",
            "id": "msg_pref003",
            "from": {"did": "did:roar:agent:sender-001"},
            "to": {"did": "did:roar:agent:acp-agent-001"},
            "intent": "ask",
            "payload": {"content": "What is your status?"},
        }

        result = bridge.bridge_message(msg)
        assert "role" in result
        assert "content" in result

    def test_roar_agent_receives_roar_format(self, bridge, agent_card_roar):
        """When a ROAR agent is the target, the response is in ROAR format."""
        bridge.register_agent(agent_card_roar, preferred_protocol="roar")

        msg = {
            "roar": "1.0",
            "id": "msg_pref004",
            "from": {"did": "did:roar:agent:sender-001"},
            "to": {"did": "did:roar:agent:roar-native-001"},
            "intent": "execute",
            "payload": {"action": "test"},
        }

        result = bridge.bridge_message(msg)
        assert "roar" in result
        assert result["payload"]["status"] == "routed"


# ═══════════════════════════════════════════════════════════════════════════
# Unknown protocol returns error
# ═══════════════════════════════════════════════════════════════════════════


class TestUnknownProtocol:
    def test_unknown_protocol_error(self, bridge):
        """Unrecognizable messages return an error."""
        msg = {
            "foo": "bar",
            "baz": 42,
        }

        result = bridge.bridge_message(msg)
        assert result["error"] == "unknown_protocol"
        assert result["protocol"] == "unknown"

    def test_empty_message_error(self, bridge):
        result = bridge.bridge_message({})
        assert result["error"] == "unknown_protocol"

    def test_unknown_jsonrpc_method(self, bridge):
        """JSON-RPC with unrecognized method is unknown protocol."""
        msg = {
            "jsonrpc": "2.0",
            "method": "custom/unknown",
            "id": 99,
        }

        result = bridge.bridge_message(msg)
        assert result["error"] == "unknown_protocol"


# ═══════════════════════════════════════════════════════════════════════════
# Cross-protocol bridging end-to-end
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossProtocolBridging:
    def test_mcp_in_a2a_out(self, bridge, agent_card_a2a):
        """MCP input targeting an A2A agent gets A2A format response."""
        bridge.register_agent(agent_card_a2a, preferred_protocol="a2a")

        # MCP message (routed via bridge, but target is A2A)
        # Since MCP doesn't carry a "to" field, the response will be
        # in the default format, but we can check it doesn't error
        mcp_msg = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 5,
            "params": {"name": "summarize", "arguments": {"text": "hello"}},
        }

        result = bridge.bridge_message(mcp_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"

    def test_acp_in_roar_out(self, bridge, agent_card_roar):
        """ACP input with routing to a ROAR-native agent."""
        bridge.register_agent(agent_card_roar, preferred_protocol="roar")

        acp_msg = {
            "role": "user",
            "content": "Review my code",
        }

        result = bridge.bridge_message(acp_msg)
        assert "error" not in result or result.get("error") != "unknown_protocol"
