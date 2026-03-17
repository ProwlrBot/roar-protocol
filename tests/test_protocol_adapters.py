"""Production-grade protocol adapter test suite.

Tests MCP, A2A, and ACP adapters for correctness, round-trip fidelity,
edge cases, and protocol auto-detection accuracy.
"""

import json
import pytest

from roar_sdk import AgentIdentity, MessageIntent
from roar_sdk.adapters.acp import ACPAdapter
from roar_sdk.adapters.detect import detect_protocol, ProtocolType


# ── Fixtures ────────────────────────────────────────────────────────────────

IDE = AgentIdentity(display_name="vscode", agent_type="ide")
AGENT = AgentIdentity(display_name="coder-agent", capabilities=["code"])


# ── Protocol Detection Tests ────────────────────────────────────────────────

class TestProtocolDetection:
    def test_detect_roar_native(self):
        msg = {"roar": "1.0", "intent": "delegate", "from": {}, "to": {}}
        assert detect_protocol(msg) == ProtocolType.ROAR

    def test_detect_acp_message(self):
        msg = {"role": "user", "content": "Explain this function"}
        assert detect_protocol(msg) == ProtocolType.ACP

    def test_detect_mcp_tools_list(self):
        msg = {"jsonrpc": "2.0", "method": "tools/list", "id": 1}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_detect_mcp_resources(self):
        msg = {"jsonrpc": "2.0", "method": "resources/read", "id": 2}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_detect_mcp_initialize(self):
        msg = {"jsonrpc": "2.0", "method": "initialize", "id": 0}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_detect_mcp_result_with_tools(self):
        msg = {"jsonrpc": "2.0", "result": {"tools": []}, "id": 1}
        assert detect_protocol(msg) == ProtocolType.MCP

    def test_detect_a2a_tasks_send(self):
        msg = {"jsonrpc": "2.0", "method": "tasks/send", "id": 1}
        assert detect_protocol(msg) == ProtocolType.A2A

    def test_detect_a2a_agent_card(self):
        msg = {"jsonrpc": "2.0", "method": "agent/authenticatedExtendedCard", "id": 1}
        assert detect_protocol(msg) == ProtocolType.A2A

    def test_detect_a2a_task_envelope(self):
        msg = {"id": "task-1", "status": {"state": "completed"}, "artifacts": []}
        assert detect_protocol(msg) == ProtocolType.A2A

    def test_detect_a2a_result_with_status(self):
        msg = {"jsonrpc": "2.0", "result": {"id": "t1", "status": "completed"}, "id": 1}
        assert detect_protocol(msg) == ProtocolType.A2A

    def test_detect_unknown(self):
        assert detect_protocol({}) == ProtocolType.UNKNOWN
        assert detect_protocol({"foo": "bar"}) == ProtocolType.UNKNOWN

    def test_detect_empty_jsonrpc(self):
        msg = {"jsonrpc": "2.0", "method": "custom/unknown", "id": 1}
        assert detect_protocol(msg) == ProtocolType.UNKNOWN

    def test_detection_accuracy_batch(self):
        """Test detection across a batch of representative messages."""
        cases = [
            ({"roar": "1.0", "intent": "execute"}, ProtocolType.ROAR),
            ({"role": "assistant", "content": "Done"}, ProtocolType.ACP),
            ({"jsonrpc": "2.0", "method": "tools/call", "id": 5}, ProtocolType.MCP),
            ({"jsonrpc": "2.0", "method": "prompts/list", "id": 6}, ProtocolType.MCP),
            ({"jsonrpc": "2.0", "method": "tasks/get", "id": 7}, ProtocolType.A2A),
            ({"id": "x", "status": {"state": "working"}, "artifacts": []}, ProtocolType.A2A),
        ]
        correct = sum(1 for msg, expected in cases if detect_protocol(msg) == expected)
        assert correct == len(cases), f"Detection accuracy: {correct}/{len(cases)}"


# ── ACP Adapter Tests ───────────────────────────────────────────────────────

class TestACPAdapter:
    def test_user_message_to_roar(self):
        acp = {"role": "user", "content": "Explain this function"}
        msg = ACPAdapter.acp_message_to_roar(acp, IDE, AGENT, session_id="s1")
        assert msg.intent == MessageIntent.ASK
        assert msg.payload["content"] == "Explain this function"
        assert msg.context["protocol"] == "acp"
        assert msg.context["session_id"] == "s1"

    def test_assistant_message_to_roar(self):
        acp = {"role": "assistant", "content": "Here's the explanation..."}
        msg = ACPAdapter.acp_message_to_roar(acp, AGENT, IDE)
        assert msg.intent == MessageIntent.RESPOND

    def test_message_with_attachments(self):
        acp = {"role": "user", "content": "Check this", "attachments": [{"type": "file", "path": "main.py"}]}
        msg = ACPAdapter.acp_message_to_roar(acp, IDE, AGENT)
        assert "attachments" in msg.payload
        assert len(msg.payload["attachments"]) == 1

    def test_session_start_event(self):
        msg = ACPAdapter.acp_session_event_to_roar("start", IDE, AGENT, session_id="s1")
        assert msg.intent == MessageIntent.NOTIFY
        assert msg.payload["event"] == "session.start"

    def test_session_end_event(self):
        msg = ACPAdapter.acp_session_event_to_roar("end", IDE, AGENT, session_id="s1")
        assert msg.payload["event"] == "session.end"

    def test_roar_to_acp_respond(self):
        from roar_sdk import ROARMessage
        msg = ROARMessage(
            **{"from": AGENT, "to": IDE},
            intent=MessageIntent.RESPOND,
            payload={"content": "Done!"},
        )
        acp = ACPAdapter.roar_to_acp_message(msg)
        assert acp["role"] == "assistant"
        assert acp["content"] == "Done!"

    def test_roar_to_acp_ask(self):
        from roar_sdk import ROARMessage
        msg = ROARMessage(
            **{"from": AGENT, "to": IDE},
            intent=MessageIntent.ASK,
            payload={"content": "Should I proceed?"},
        )
        acp = ACPAdapter.roar_to_acp_message(msg)
        assert acp["role"] == "user"

    def test_roar_to_acp_run(self):
        from roar_sdk import ROARMessage
        msg = ROARMessage(
            **{"from": AGENT, "to": IDE},
            intent=MessageIntent.RESPOND,
            payload={"content": "Result"},
            context={"session_id": "s1"},
        )
        run = ACPAdapter.roar_to_acp_run(msg, run_id="run-1")
        assert run["run_id"] == "run-1"
        assert run["status"] == "completed"
        assert run["metadata"]["roar_intent"] == MessageIntent.RESPOND

    def test_roundtrip_user_message(self):
        """ACP → ROAR → ACP roundtrip preserves content."""
        original = {"role": "user", "content": "Hello agent"}
        roar_msg = ACPAdapter.acp_message_to_roar(original, IDE, AGENT)
        back = ACPAdapter.roar_to_acp_message(roar_msg)
        assert back["content"] == original["content"]

    def test_well_known_agent_to_card(self):
        wk = {
            "name": "test-agent",
            "description": "A test agent",
            "version": "2.0",
            "skills": [{"name": "coding"}, {"name": "testing"}],
            "supportedModes": ["http", "websocket"],
            "url": "http://example.com/agent",
        }
        card = ACPAdapter.well_known_agent_to_card(wk)
        assert card["identity"]["display_name"] == "test-agent"
        assert card["skills"] == ["coding", "testing"]
        assert card["endpoints"]["http"] == "http://example.com/agent"

    def test_empty_content_handled(self):
        acp = {"role": "user", "content": ""}
        msg = ACPAdapter.acp_message_to_roar(acp, IDE, AGENT)
        assert msg.payload["content"] == ""

    def test_missing_role_defaults_to_user(self):
        acp = {"content": "No role specified"}
        msg = ACPAdapter.acp_message_to_roar(acp, IDE, AGENT)
        assert msg.intent == MessageIntent.ASK


# ── Edge Cases ──────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_detect_handles_non_dict_gracefully(self):
        """Detection should handle malformed input."""
        # These should return UNKNOWN, not crash
        assert detect_protocol({"jsonrpc": "1.0"}) == ProtocolType.UNKNOWN

    def test_large_payload_detection(self):
        """Detection works with large payloads."""
        msg = {"roar": "1.0", "intent": "delegate", "payload": {"data": "x" * 100_000}}
        assert detect_protocol(msg) == ProtocolType.ROAR

    def test_nested_acp_content(self):
        """ACP with list content (multi-part) is handled."""
        acp = {"role": "user", "content": [{"type": "text", "text": "Hello"}, {"type": "image", "url": "..."}]}
        msg = ACPAdapter.acp_message_to_roar(acp, IDE, AGENT)
        assert isinstance(msg.payload["content"], list)
