# -*- coding: utf-8 -*-
"""Tests for framework adapters (AutoGen, CrewAI, LangGraph)."""

import pytest

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.adapters.autogen import AutoGenAdapter
from roar_sdk.adapters.crewai import CrewAIAdapter
from roar_sdk.adapters.langgraph import LangGraphAdapter
from roar_sdk.adapters.detect import ProtocolType, detect_protocol


@pytest.fixture
def agent_a():
    return AgentIdentity(display_name="agent-a")

@pytest.fixture
def agent_b():
    return AgentIdentity(display_name="agent-b")


# ── AutoGen Adapter ──────────────────────────────────────────────────────────

class TestAutoGenAdapter:
    def test_user_message(self, agent_a, agent_b):
        msg = AutoGenAdapter.autogen_to_roar(
            {"role": "user", "content": "Review this code"},
            agent_a, agent_b,
        )
        assert msg.intent == MessageIntent.ASK
        assert msg.payload["content"] == "Review this code"
        assert msg.context["protocol"] == "autogen"

    def test_assistant_message(self, agent_a, agent_b):
        msg = AutoGenAdapter.autogen_to_roar(
            {"role": "assistant", "content": "Code looks good"},
            agent_a, agent_b,
        )
        assert msg.intent == MessageIntent.RESPOND

    def test_system_message(self, agent_a, agent_b):
        msg = AutoGenAdapter.autogen_to_roar(
            {"role": "system", "content": "You are a reviewer"},
            agent_a, agent_b,
        )
        assert msg.intent == MessageIntent.NOTIFY

    def test_function_message(self, agent_a, agent_b):
        msg = AutoGenAdapter.autogen_to_roar(
            {"role": "function", "content": '{"result": 42}', "name": "calc"},
            agent_a, agent_b,
        )
        assert msg.intent == MessageIntent.UPDATE
        assert msg.payload["name"] == "calc"

    def test_tool_calls_override_to_delegate(self, agent_a, agent_b):
        msg = AutoGenAdapter.autogen_to_roar(
            {"role": "assistant", "content": "", "tool_calls": [{"id": "tc1", "function": {"name": "search"}}]},
            agent_a, agent_b,
        )
        assert msg.intent == MessageIntent.DELEGATE
        assert msg.payload["tool_calls"][0]["id"] == "tc1"

    def test_round_trip_user(self, agent_a, agent_b):
        original = {"role": "user", "content": "Hello agent"}
        roar = AutoGenAdapter.autogen_to_roar(original, agent_a, agent_b)
        back = AutoGenAdapter.roar_to_autogen(roar)
        assert back["role"] == "user"
        assert back["content"] == "Hello agent"

    def test_round_trip_assistant(self, agent_a, agent_b):
        original = {"role": "assistant", "content": "Done!"}
        roar = AutoGenAdapter.autogen_to_roar(original, agent_a, agent_b)
        back = AutoGenAdapter.roar_to_autogen(roar)
        assert back["role"] == "assistant"
        assert back["content"] == "Done!"

    def test_session_id(self, agent_a, agent_b):
        msg = AutoGenAdapter.autogen_to_roar(
            {"role": "user", "content": "test"},
            agent_a, agent_b, session_id="s1",
        )
        assert msg.context["session_id"] == "s1"


# ── CrewAI Adapter ───────────────────────────────────────────────────────────

class TestCrewAIAdapter:
    def test_task_to_delegate(self, agent_a, agent_b):
        task = {
            "description": "Review PR #42",
            "expected_output": "Approval or rejection with comments",
            "agent": "senior-reviewer",
            "tools": ["git_diff", "lint"],
        }
        msg = CrewAIAdapter.crewai_task_to_roar(task, agent_a, agent_b)
        assert msg.intent == MessageIntent.DELEGATE
        assert msg.payload["task"] == "Review PR #42"
        assert msg.payload["expected_output"] == "Approval or rejection with comments"
        assert msg.payload["tools"] == ["git_diff", "lint"]
        assert msg.payload["assigned_role"] == "senior-reviewer"

    def test_result_to_respond(self, agent_a, agent_b):
        result = {"output": "Approved with minor comments", "status": "completed"}
        msg = CrewAIAdapter.crewai_result_to_roar(result, agent_a, agent_b, in_reply_to="msg-1")
        assert msg.intent == MessageIntent.RESPOND
        assert msg.payload["result"] == "Approved with minor comments"
        assert msg.context["in_reply_to"] == "msg-1"

    def test_round_trip_task(self, agent_a, agent_b):
        original = {"description": "Analyze data", "expected_output": "Summary report", "tools": ["pandas"]}
        roar = CrewAIAdapter.crewai_task_to_roar(original, agent_a, agent_b)
        back = CrewAIAdapter.roar_to_crewai_task(roar)
        assert back["description"] == "Analyze data"
        assert back["expected_output"] == "Summary report"
        assert back["tools"] == ["pandas"]

    def test_round_trip_result(self, agent_a, agent_b):
        result = {"output": "All tests pass", "status": "completed"}
        roar = CrewAIAdapter.crewai_result_to_roar(result, agent_a, agent_b)
        back = CrewAIAdapter.roar_to_crewai_result(roar)
        assert back["output"] == "All tests pass"
        assert back["status"] == "completed"

    def test_empty_task(self, agent_a, agent_b):
        msg = CrewAIAdapter.crewai_task_to_roar({}, agent_a, agent_b)
        assert msg.intent == MessageIntent.DELEGATE
        assert msg.payload["task"] == ""


# ── LangGraph Adapter ────────────────────────────────────────────────────────

class TestLangGraphAdapter:
    def test_in_progress_state(self, agent_a, agent_b):
        state = {"messages": [{"role": "user", "content": "Go"}], "next": "reviewer"}
        msg = LangGraphAdapter.langgraph_state_to_roar(state, agent_a, agent_b)
        assert msg.intent == MessageIntent.UPDATE
        assert msg.payload["next_node"] == "reviewer"
        assert msg.payload["message_count"] == 1

    def test_final_state(self, agent_a, agent_b):
        state = {"messages": [{"role": "assistant", "content": "Done"}], "next": None}
        msg = LangGraphAdapter.langgraph_state_to_roar(state, agent_a, agent_b)
        assert msg.intent == MessageIntent.RESPOND
        assert msg.payload["content"] == "Done"

    def test_end_node(self, agent_a, agent_b):
        state = {"messages": [], "next": "__end__"}
        msg = LangGraphAdapter.langgraph_state_to_roar(state, agent_a, agent_b)
        assert msg.intent == MessageIntent.RESPOND

    def test_interrupt_state(self, agent_a, agent_b):
        state = {"messages": [{"role": "assistant", "content": "Need input"}], "next": "__interrupt__"}
        msg = LangGraphAdapter.langgraph_state_to_roar(state, agent_a, agent_b)
        assert msg.intent == MessageIntent.ASK

    def test_invoke_to_delegate(self, agent_a, agent_b):
        msgs = [{"role": "user", "content": "Start task"}]
        msg = LangGraphAdapter.langgraph_invoke_to_roar(msgs, agent_a, agent_b, graph_name="review")
        assert msg.intent == MessageIntent.DELEGATE
        assert msg.payload["content"] == "Start task"
        assert msg.payload["graph"] == "review"

    def test_round_trip_state(self, agent_a, agent_b):
        state = {"messages": [{"role": "assistant", "content": "Result"}], "next": None}
        roar = LangGraphAdapter.langgraph_state_to_roar(state, agent_a, agent_b)
        back = LangGraphAdapter.roar_to_langgraph_state(roar)
        assert back["next"] is None  # RESPOND → final state

    def test_state_with_metadata(self, agent_a, agent_b):
        state = {"messages": [], "next": "step2", "metadata": {"graph_id": "g1"}}
        msg = LangGraphAdapter.langgraph_state_to_roar(state, agent_a, agent_b)
        assert msg.payload["graph_metadata"]["graph_id"] == "g1"


# ── Framework Detection ──────────────────────────────────────────────────────

class TestFrameworkDetection:
    def test_detect_autogen_tool_calls(self):
        msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "t1"}]}
        assert detect_protocol(msg) == ProtocolType.AUTOGEN

    def test_detect_autogen_function_call(self):
        msg = {"role": "assistant", "content": "", "function_call": {"name": "calc"}}
        assert detect_protocol(msg) == ProtocolType.AUTOGEN

    def test_detect_crewai_task(self):
        msg = {"description": "Do something", "expected_output": "Result"}
        assert detect_protocol(msg) == ProtocolType.CREWAI

    def test_detect_langgraph_state(self):
        msg = {"messages": [{"role": "user", "content": "go"}], "next": "step1"}
        assert detect_protocol(msg) == ProtocolType.LANGGRAPH
