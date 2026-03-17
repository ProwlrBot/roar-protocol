# -*- coding: utf-8 -*-
"""Tests for the ROAR MCP protocol adapter."""

import json

import pytest

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.adapters.mcp import MCPAdapter
from roar_sdk.types import AgentCapability, AgentCard


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def host_agent():
    return AgentIdentity(display_name="claude-desktop", agent_type="ide")


@pytest.fixture
def server_agent():
    return AgentIdentity(display_name="file-server", agent_type="tool")


# ── MCP → ROAR: tools/call ──────────────────────────────────────────────────


class TestMCPToROARToolsCall:
    def test_tools_call_basic(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "/tmp/x.txt"}},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.EXECUTE
        assert msg.payload["tool"] == "read_file"
        assert msg.payload["arguments"] == {"path": "/tmp/x.txt"}
        assert msg.context["protocol"] == "mcp"
        assert msg.context["method"] == "tools/call"
        assert msg.context["request_id"] == 1

    def test_tools_call_empty_arguments(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_time"},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.EXECUTE
        assert msg.payload["tool"] == "get_time"
        assert msg.payload["arguments"] == {}

    def test_tools_call_complex_arguments(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search",
                "arguments": {
                    "query": "test",
                    "filters": {"type": "file", "limit": 10},
                    "tags": ["a", "b"],
                },
            },
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.payload["arguments"]["filters"] == {"type": "file", "limit": 10}
        assert msg.payload["arguments"]["tags"] == ["a", "b"]

    def test_tools_call_missing_name(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.EXECUTE
        assert msg.payload["tool"] == ""


# ── MCP → ROAR: tools/list ──────────────────────────────────────────────────


class TestMCPToROARToolsList:
    def test_tools_list(self, host_agent, server_agent):
        mcp = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.DISCOVER
        assert msg.payload["type"] == "tools"
        assert msg.context["method"] == "tools/list"

    def test_tools_list_no_params(self, host_agent, server_agent):
        mcp = {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": None}
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.DISCOVER
        assert msg.payload["type"] == "tools"


# ── MCP → ROAR: resources/read ──────────────────────────────────────────────


class TestMCPToROARResourcesRead:
    def test_resources_read(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "resources/read",
            "params": {"uri": "file:///tmp/data.csv"},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.EXECUTE
        assert msg.payload["resource"] == "file:///tmp/data.csv"
        assert msg.context["method"] == "resources/read"

    def test_resources_read_missing_uri(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "resources/read",
            "params": {},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.EXECUTE
        assert msg.payload["resource"] == ""


# ── MCP → ROAR: prompts/get ─────────────────────────────────────────────────


class TestMCPToROARPromptsGet:
    def test_prompts_get(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "prompts/get",
            "params": {"name": "summarize", "arguments": {"style": "brief"}},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.ASK
        assert msg.payload["prompt"] == "summarize"
        assert msg.payload["arguments"] == {"style": "brief"}

    def test_prompts_get_no_arguments(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "prompts/get",
            "params": {"name": "greeting"},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.ASK
        assert msg.payload["prompt"] == "greeting"
        assert msg.payload["arguments"] == {}


# ── MCP → ROAR: initialize ──────────────────────────────────────────────────


class TestMCPToROARInitialize:
    def test_initialize(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "claude-desktop", "version": "1.0"},
            },
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.NOTIFY
        assert msg.payload["event"] == "initialize"
        assert msg.payload["protocolVersion"] == "2024-11-05"

    def test_initialize_no_params(self, host_agent, server_agent):
        mcp = {"jsonrpc": "2.0", "id": 0, "method": "initialize"}
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.NOTIFY
        assert msg.payload["event"] == "initialize"


# ── MCP → ROAR: notifications/* ─────────────────────────────────────────────


class TestMCPToROARNotifications:
    def test_notification_initialized(self, host_agent, server_agent):
        mcp = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.NOTIFY
        assert msg.payload["event"] == "initialized"

    def test_notification_cancelled(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 5, "reason": "user cancelled"},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.NOTIFY
        assert msg.payload["event"] == "cancelled"
        assert msg.payload["requestId"] == 5
        assert msg.payload["reason"] == "user cancelled"

    def test_notification_no_request_id(self, host_agent, server_agent):
        """Notifications typically have no id field."""
        mcp = {"jsonrpc": "2.0", "method": "notifications/progress"}
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert "request_id" not in msg.context


# ── MCP → ROAR: unknown methods ─────────────────────────────────────────────


class TestMCPToROARUnknownMethod:
    def test_unknown_method_fallback(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "custom/doSomething",
            "params": {"key": "value"},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, from_agent=host_agent, to_agent=server_agent)
        assert msg.intent == MessageIntent.EXECUTE
        assert msg.payload["method"] == "custom/doSomething"
        assert msg.payload["key"] == "value"


# ── ROAR → MCP: tool result response ────────────────────────────────────────


class TestROARToMCPResult:
    def test_respond_with_result_string(self, host_agent, server_agent):
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"result": "File contents here"},
            context={"protocol": "mcp", "request_id": 1},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=1)
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"]["content"] == [{"type": "text", "text": "File contents here"}]

    def test_respond_with_content_string(self, host_agent, server_agent):
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"content": "Hello world"},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=2)
        assert resp["result"]["content"] == [{"type": "text", "text": "Hello world"}]
        assert resp["id"] == 2

    def test_respond_with_content_array_passthrough(self, host_agent, server_agent):
        """If content is already an MCP content array, pass it through."""
        content_array = [
            {"type": "text", "text": "part 1"},
            {"type": "text", "text": "part 2"},
        ]
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"content": content_array},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=3)
        assert resp["result"]["content"] == content_array

    def test_respond_uses_context_request_id(self, host_agent, server_agent):
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"result": "ok"},
            context={"protocol": "mcp", "request_id": 42},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg)
        assert resp["id"] == 42

    def test_respond_explicit_id_overrides_context(self, host_agent, server_agent):
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"result": "ok"},
            context={"protocol": "mcp", "request_id": 42},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=99)
        assert resp["id"] == 99

    def test_respond_empty_payload(self, host_agent, server_agent):
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=5)
        assert resp["jsonrpc"] == "2.0"
        # Empty payload serialized as JSON
        assert resp["result"]["content"][0]["type"] == "text"


# ── ROAR → MCP: tool list response ──────────────────────────────────────────


class TestROARToMCPToolList:
    def test_respond_with_tools_list(self, host_agent, server_agent):
        tools = [
            {"name": "read_file", "description": "Read a file", "inputSchema": {}},
            {"name": "write_file", "description": "Write a file", "inputSchema": {}},
        ]
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"tools": tools},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=1)
        assert resp["jsonrpc"] == "2.0"
        assert resp["result"]["tools"] == tools
        assert resp["id"] == 1

    def test_respond_with_empty_tools_list(self, host_agent, server_agent):
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"tools": []},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=1)
        assert resp["result"]["tools"] == []


# ── Agent Card ↔ MCP Tool ───────────────────────────────────────────────────


class TestAgentCardToMCPTool:
    def test_card_to_tool_basic(self):
        card = AgentCard(
            identity=AgentIdentity(display_name="read_file", agent_type="tool"),
            description="Read a file from disk",
            declared_capabilities=[
                AgentCapability(
                    name="read_file",
                    description="Read a file from disk",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                )
            ],
        )
        tool = MCPAdapter.agent_card_to_mcp_tool(card)
        assert tool["name"] == "read_file"
        assert tool["description"] == "Read a file from disk"
        assert tool["inputSchema"]["properties"]["path"]["type"] == "string"
        assert "path" in tool["inputSchema"]["required"]

    def test_card_to_tool_no_capabilities(self):
        card = AgentCard(
            identity=AgentIdentity(display_name="simple-agent", agent_type="agent"),
            description="A simple agent",
        )
        tool = MCPAdapter.agent_card_to_mcp_tool(card)
        assert tool["name"] == "simple-agent"
        assert tool["description"] == "A simple agent"
        assert tool["inputSchema"] == {"type": "object", "properties": {}}

    def test_card_to_tool_no_description(self):
        card = AgentCard(
            identity=AgentIdentity(display_name="mystery-tool", agent_type="tool"),
        )
        tool = MCPAdapter.agent_card_to_mcp_tool(card)
        assert tool["description"] == "Agent: mystery-tool"


class TestMCPToolToAgentCard:
    def test_tool_to_card_basic(self):
        tool = {
            "name": "search_files",
            "description": "Search for files by pattern",
            "inputSchema": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}},
            },
        }
        card = MCPAdapter.mcp_tool_to_agent_card(tool)
        assert card.identity.display_name == "search_files"
        assert card.identity.agent_type == "tool"
        assert card.description == "Search for files by pattern"
        assert "search_files" in card.skills
        assert "search_files" in card.identity.capabilities
        assert card.metadata["protocol"] == "mcp"
        assert len(card.declared_capabilities) == 1
        assert card.declared_capabilities[0].input_schema == tool["inputSchema"]

    def test_tool_to_card_missing_fields(self):
        tool = {}
        card = MCPAdapter.mcp_tool_to_agent_card(tool)
        assert card.identity.display_name == "unknown-tool"
        assert card.description == ""
        assert card.declared_capabilities == []

    def test_tool_to_card_no_schema(self):
        tool = {"name": "ping", "description": "Ping the server"}
        card = MCPAdapter.mcp_tool_to_agent_card(tool)
        assert card.identity.display_name == "ping"
        assert card.declared_capabilities == []


# ── Round-trip tests ─────────────────────────────────────────────────────────


class TestRoundTrip:
    def test_tools_call_round_trip(self, host_agent, server_agent):
        """MCP tools/call → ROAR → MCP response preserves semantics."""
        mcp_req = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {"path": "/etc/hosts"}},
        }
        roar_msg = MCPAdapter.mcp_to_roar(mcp_req, host_agent, server_agent)

        # Simulate tool execution: create a response
        response_msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"result": "127.0.0.1 localhost"},
            context=roar_msg.context,
        )
        mcp_resp = MCPAdapter.roar_to_mcp_result(response_msg, request_id=mcp_req["id"])

        assert mcp_resp["jsonrpc"] == "2.0"
        assert mcp_resp["id"] == 7
        assert mcp_resp["result"]["content"][0]["text"] == "127.0.0.1 localhost"

    def test_tools_list_round_trip(self, host_agent, server_agent):
        """MCP tools/list → ROAR → MCP response preserves semantics."""
        mcp_req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        roar_msg = MCPAdapter.mcp_to_roar(mcp_req, host_agent, server_agent)

        assert roar_msg.intent == MessageIntent.DISCOVER

        tools = [{"name": "echo", "description": "Echo input", "inputSchema": {}}]
        response_msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"tools": tools},
            context=roar_msg.context,
        )
        mcp_resp = MCPAdapter.roar_to_mcp_result(response_msg, request_id=1)

        assert mcp_resp["result"]["tools"] == tools

    def test_agent_card_round_trip(self):
        """AgentCard → MCP tool → AgentCard preserves key fields."""
        original_card = AgentCard(
            identity=AgentIdentity(display_name="calculator", agent_type="tool", capabilities=["calculator"]),
            description="Perform calculations",
            skills=["calculator"],
            declared_capabilities=[
                AgentCapability(
                    name="calculator",
                    description="Perform calculations",
                    input_schema={
                        "type": "object",
                        "properties": {"expression": {"type": "string"}},
                        "required": ["expression"],
                    },
                )
            ],
        )

        # Card → MCP tool → Card
        mcp_tool = MCPAdapter.agent_card_to_mcp_tool(original_card)
        restored_card = MCPAdapter.mcp_tool_to_agent_card(mcp_tool)

        assert restored_card.identity.display_name == original_card.identity.display_name
        assert restored_card.description == original_card.description
        assert restored_card.declared_capabilities[0].input_schema == (
            original_card.declared_capabilities[0].input_schema
        )

    def test_prompts_get_round_trip(self, host_agent, server_agent):
        """MCP prompts/get → ROAR → MCP response preserves semantics."""
        mcp_req = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "prompts/get",
            "params": {"name": "summarize", "arguments": {"length": "short"}},
        }
        roar_msg = MCPAdapter.mcp_to_roar(mcp_req, host_agent, server_agent)

        assert roar_msg.intent == MessageIntent.ASK
        assert roar_msg.payload["prompt"] == "summarize"

        response_msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"content": "Here is a brief summary..."},
            context=roar_msg.context,
        )
        mcp_resp = MCPAdapter.roar_to_mcp_result(response_msg, request_id=20)

        assert mcp_resp["id"] == 20
        assert mcp_resp["result"]["content"][0]["text"] == "Here is a brief summary..."


# ── Edge cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_method(self, host_agent, server_agent):
        """Message with no method field falls through to unknown handler."""
        mcp = {"jsonrpc": "2.0", "id": 1}
        msg = MCPAdapter.mcp_to_roar(mcp, host_agent, server_agent)
        assert msg.intent == MessageIntent.EXECUTE
        assert msg.payload.get("method") == ""

    def test_empty_params(self, host_agent, server_agent):
        mcp = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
        msg = MCPAdapter.mcp_to_roar(mcp, host_agent, server_agent)
        assert msg.payload["tool"] == ""
        assert msg.payload["arguments"] == {}

    def test_null_params(self, host_agent, server_agent):
        mcp = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": None}
        msg = MCPAdapter.mcp_to_roar(mcp, host_agent, server_agent)
        assert msg.intent == MessageIntent.DISCOVER

    def test_preserves_from_to_identities(self, host_agent, server_agent):
        mcp = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "test"},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, host_agent, server_agent)
        assert msg.from_identity.display_name == "claude-desktop"
        assert msg.to_identity.display_name == "file-server"

    def test_string_request_id(self, host_agent, server_agent):
        """JSON-RPC allows string IDs."""
        mcp = {
            "jsonrpc": "2.0",
            "id": "req-abc-123",
            "method": "tools/call",
            "params": {"name": "test"},
        }
        msg = MCPAdapter.mcp_to_roar(mcp, host_agent, server_agent)
        assert msg.context["request_id"] == "req-abc-123"

        resp = MCPAdapter.roar_to_mcp_result(msg, request_id="req-abc-123")
        assert resp["id"] == "req-abc-123"

    def test_result_with_non_string_value(self, host_agent, server_agent):
        """Non-string result values should be converted to string."""
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"result": 42},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=1)
        assert resp["result"]["content"][0]["text"] == "42"

    def test_result_with_dict_payload(self, host_agent, server_agent):
        """Payload with no result/content keys serializes full payload."""
        msg = ROARMessage(
            **{"from": server_agent, "to": host_agent},
            intent=MessageIntent.RESPOND,
            payload={"status": "ok", "count": 3},
        )
        resp = MCPAdapter.roar_to_mcp_result(msg, request_id=1)
        text = resp["result"]["content"][0]["text"]
        parsed = json.loads(text)
        assert parsed["status"] == "ok"
        assert parsed["count"] == 3
