# -*- coding: utf-8 -*-
"""Tests for the ROAR A2A (Agent-to-Agent) protocol adapter."""

import pytest

from roar_sdk import AgentIdentity, MessageIntent, ROARMessage
from roar_sdk.adapters.a2a import A2AAdapter
from roar_sdk.types import AgentCard, AgentCapability


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def orchestrator():
    return AgentIdentity(display_name="orchestrator", agent_type="agent")


@pytest.fixture
def worker():
    return AgentIdentity(display_name="worker-agent", agent_type="agent")


@pytest.fixture
def sample_a2a_tasks_send():
    return {
        "jsonrpc": "2.0",
        "method": "tasks/send",
        "id": 1,
        "params": {
            "id": "task-42",
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": "Summarize this document"}],
            },
        },
    }


@pytest.fixture
def sample_a2a_tasks_get():
    return {
        "jsonrpc": "2.0",
        "method": "tasks/get",
        "id": 2,
        "params": {"id": "task-42"},
    }


@pytest.fixture
def sample_a2a_tasks_cancel():
    return {
        "jsonrpc": "2.0",
        "method": "tasks/cancel",
        "id": 3,
        "params": {"id": "task-42"},
    }


@pytest.fixture
def sample_a2a_agent_card_request():
    return {
        "jsonrpc": "2.0",
        "method": "agent/authenticatedExtendedCard",
        "id": 4,
        "params": {},
    }


@pytest.fixture
def sample_roar_agent_card():
    identity = AgentIdentity(
        display_name="summarizer",
        agent_type="agent",
        capabilities=["summarize", "translate"],
        version="2.0",
    )
    return AgentCard(
        identity=identity,
        description="An agent that summarizes documents",
        skills=["summarize", "translate"],
        channels=["http"],
        endpoints={"http": "https://summarizer.example.com"},
        declared_capabilities=[
            AgentCapability(name="extract", description="Extract key points"),
        ],
    )


@pytest.fixture
def sample_a2a_agent_card():
    return {
        "name": "researcher",
        "description": "A research assistant agent",
        "url": "https://researcher.example.com",
        "version": "1.5",
        "skills": [
            {"id": "skill-0", "name": "search", "description": "Web search"},
            {"id": "skill-1", "name": "cite", "description": "Citation formatting"},
        ],
    }


# ── A2A → ROAR: tasks/send ──────────────────────────────────────────────────


class TestA2ATasksSendToRoar:
    def test_basic_tasks_send(self, sample_a2a_tasks_send, orchestrator, worker):
        msg = A2AAdapter.a2a_to_roar(sample_a2a_tasks_send, orchestrator, worker)
        assert msg.intent == MessageIntent.DELEGATE
        assert msg.payload["task_id"] == "task-42"
        assert msg.payload["content"] == "Summarize this document"
        assert msg.context["protocol"] == "a2a"
        assert msg.context["task_id"] == "task-42"

    def test_tasks_send_preserves_a2a_message(self, sample_a2a_tasks_send, orchestrator, worker):
        msg = A2AAdapter.a2a_to_roar(sample_a2a_tasks_send, orchestrator, worker)
        assert msg.payload["a2a_message"]["role"] == "user"
        assert msg.payload["a2a_message"]["parts"][0]["type"] == "text"

    def test_tasks_send_multi_part(self, orchestrator, worker):
        a2a = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": "task-99",
                "message": {
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": "First part."},
                        {"type": "text", "text": "Second part."},
                    ],
                },
            },
        }
        msg = A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)
        assert msg.payload["content"] == "First part.\nSecond part."

    def test_tasks_send_empty_parts(self, orchestrator, worker):
        a2a = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": "task-empty",
                "message": {"role": "user", "parts": []},
            },
        }
        msg = A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)
        assert msg.payload["content"] == ""
        assert msg.intent == MessageIntent.DELEGATE

    def test_tasks_send_non_text_parts_ignored(self, orchestrator, worker):
        a2a = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": "task-mixed",
                "message": {
                    "role": "user",
                    "parts": [
                        {"type": "text", "text": "Hello"},
                        {"type": "image", "data": "base64..."},
                        {"type": "text", "text": "World"},
                    ],
                },
            },
        }
        msg = A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)
        assert msg.payload["content"] == "Hello\nWorld"

    def test_tasks_send_no_message(self, orchestrator, worker):
        a2a = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {"id": "task-no-msg"},
        }
        msg = A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)
        assert msg.intent == MessageIntent.DELEGATE
        assert msg.payload["task_id"] == "task-no-msg"
        assert msg.payload["content"] == ""

    def test_tasks_send_agent_identities(self, sample_a2a_tasks_send, orchestrator, worker):
        msg = A2AAdapter.a2a_to_roar(sample_a2a_tasks_send, orchestrator, worker)
        assert msg.from_identity.display_name == "orchestrator"
        assert msg.to_identity.display_name == "worker-agent"


# ── A2A → ROAR: tasks/get ───────────────────────────────────────────────────


class TestA2ATasksGetToRoar:
    def test_basic_tasks_get(self, sample_a2a_tasks_get, orchestrator, worker):
        msg = A2AAdapter.a2a_to_roar(sample_a2a_tasks_get, orchestrator, worker)
        assert msg.intent == MessageIntent.ASK
        assert msg.payload["task_id"] == "task-42"
        assert msg.payload["query"] == "status"
        assert msg.context["protocol"] == "a2a"

    def test_tasks_get_preserves_task_id_in_context(self, sample_a2a_tasks_get, orchestrator, worker):
        msg = A2AAdapter.a2a_to_roar(sample_a2a_tasks_get, orchestrator, worker)
        assert msg.context["task_id"] == "task-42"


# ── A2A → ROAR: tasks/cancel ────────────────────────────────────────────────


class TestA2ATasksCancelToRoar:
    def test_basic_tasks_cancel(self, sample_a2a_tasks_cancel, orchestrator, worker):
        msg = A2AAdapter.a2a_to_roar(sample_a2a_tasks_cancel, orchestrator, worker)
        assert msg.intent == MessageIntent.NOTIFY
        assert msg.payload["event"] == "task.cancel"
        assert msg.payload["task_id"] == "task-42"

    def test_tasks_cancel_context(self, sample_a2a_tasks_cancel, orchestrator, worker):
        msg = A2AAdapter.a2a_to_roar(sample_a2a_tasks_cancel, orchestrator, worker)
        assert msg.context["protocol"] == "a2a"
        assert msg.context["task_id"] == "task-42"


# ── A2A → ROAR: agent/authenticatedExtendedCard ─────────────────────────────


class TestA2AAgentCardRequestToRoar:
    def test_agent_card_request(self, sample_a2a_agent_card_request, orchestrator, worker):
        msg = A2AAdapter.a2a_to_roar(sample_a2a_agent_card_request, orchestrator, worker)
        assert msg.intent == MessageIntent.DISCOVER
        assert msg.payload["query"] == "agent_card"
        assert msg.context["protocol"] == "a2a"


# ── A2A → ROAR: bare task envelope ──────────────────────────────────────────


class TestA2ABareTaskEnvelopeToRoar:
    def test_bare_task_envelope(self, orchestrator, worker):
        task = {"id": "task-77", "status": {"state": "submitted"}, "artifacts": []}
        msg = A2AAdapter.a2a_to_roar(task, orchestrator, worker)
        assert msg.intent == MessageIntent.DELEGATE
        assert msg.payload["id"] == "task-77"
        assert msg.context["task_id"] == "task-77"


# ── A2A → ROAR: unknown method ──────────────────────────────────────────────


class TestA2AUnknownMethod:
    def test_unknown_method_raises(self, orchestrator, worker):
        a2a = {
            "jsonrpc": "2.0",
            "method": "unknown/method",
            "id": 1,
            "params": {},
        }
        with pytest.raises(ValueError, match="Unknown A2A method"):
            A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)


# ── ROAR → A2A: task response ───────────────────────────────────────────────


class TestRoarToA2ATask:
    def test_respond_to_completed(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"content": "Here is the summary."},
            context={"protocol": "a2a", "task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["id"] == "task-42"
        assert task["status"]["state"] == "completed"
        assert len(task["artifacts"]) == 1
        assert task["artifacts"][0]["parts"][0]["type"] == "text"
        assert task["artifacts"][0]["parts"][0]["text"] == "Here is the summary."

    def test_respond_with_explicit_task_id(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"content": "Done"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg, task_id="override-id")
        assert task["id"] == "override-id"

    def test_respond_uses_result_field(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"result": "Some result"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg, task_id="t1")
        assert task["artifacts"][0]["parts"][0]["text"] == "Some result"

    def test_respond_empty_content(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={},
        )
        task = A2AAdapter.roar_to_a2a_task(msg, task_id="t1")
        assert task["status"]["state"] == "completed"
        assert task["artifacts"][0]["parts"][0]["text"] == ""

    def test_update_to_working(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.UPDATE,
            payload={"content": "Processing step 2 of 5"},
            context={"protocol": "a2a", "task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["id"] == "task-42"
        assert task["status"]["state"] == "working"
        assert "artifacts" not in task
        assert task["status"]["message"]["role"] == "agent"
        assert task["status"]["message"]["parts"][0]["text"] == "Processing step 2 of 5"

    def test_update_without_content(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.UPDATE,
            payload={},
            context={"task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["status"]["state"] == "working"
        assert "message" not in task["status"]

    def test_notify_cancel_to_failed(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.NOTIFY,
            payload={"event": "task.cancel", "task_id": "task-42"},
            context={"task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["status"]["state"] == "failed"

    def test_notify_failure_to_failed(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.NOTIFY,
            payload={"event": "task.failure", "reason": "Out of memory"},
            context={"task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["status"]["state"] == "failed"
        assert task["status"]["message"]["parts"][0]["text"] == "Out of memory"

    def test_notify_error_event(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.NOTIFY,
            payload={"event": "task.error"},
            context={"task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["status"]["state"] == "failed"

    def test_notify_generic_to_submitted(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.NOTIFY,
            payload={"event": "task.created"},
            context={"task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["status"]["state"] == "submitted"

    def test_delegate_to_submitted(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.DELEGATE,
            payload={"task_id": "task-42", "content": "Do this"},
            context={"task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["status"]["state"] == "submitted"

    def test_ask_to_submitted(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.ASK,
            payload={"task_id": "task-42"},
            context={"task_id": "task-42"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["status"]["state"] == "submitted"

    def test_task_id_fallback_to_msg_id(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"content": "Done"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["id"] == msg.id


# ── ROAR → A2A: JSON-RPC response ───────────────────────────────────────────


class TestRoarToA2AJsonRpcResponse:
    def test_jsonrpc_response_wrapping(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"content": "All done"},
        )
        resp = A2AAdapter.roar_to_a2a_jsonrpc_response(msg, request_id=5, task_id="task-42")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 5
        assert resp["result"]["id"] == "task-42"
        assert resp["result"]["status"]["state"] == "completed"

    def test_jsonrpc_response_default_request_id(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.UPDATE,
            payload={},
        )
        resp = A2AAdapter.roar_to_a2a_jsonrpc_response(msg, task_id="t1")
        assert resp["id"] == 1


# ── Agent Card: ROAR → A2A ──────────────────────────────────────────────────


class TestRoarToA2AAgentCard:
    def test_basic_card_conversion(self, sample_roar_agent_card):
        a2a_card = A2AAdapter.roar_to_a2a_agent_card(sample_roar_agent_card)
        assert a2a_card["name"] == "summarizer"
        assert a2a_card["description"] == "An agent that summarizes documents"
        assert a2a_card["url"] == "https://summarizer.example.com"
        assert a2a_card["version"] == "2.0"

    def test_skills_from_skills_list(self, sample_roar_agent_card):
        a2a_card = A2AAdapter.roar_to_a2a_agent_card(sample_roar_agent_card)
        skill_names = [s["name"] for s in a2a_card["skills"]]
        assert "summarize" in skill_names
        assert "translate" in skill_names

    def test_skills_from_declared_capabilities(self, sample_roar_agent_card):
        a2a_card = A2AAdapter.roar_to_a2a_agent_card(sample_roar_agent_card)
        skill_names = [s["name"] for s in a2a_card["skills"]]
        assert "extract" in skill_names
        # Verify the extract skill has its description
        extract_skill = [s for s in a2a_card["skills"] if s["name"] == "extract"][0]
        assert extract_skill["description"] == "Extract key points"

    def test_skills_have_ids(self, sample_roar_agent_card):
        a2a_card = A2AAdapter.roar_to_a2a_agent_card(sample_roar_agent_card)
        for skill in a2a_card["skills"]:
            assert "id" in skill

    def test_empty_card(self):
        identity = AgentIdentity(display_name="minimal")
        card = AgentCard(identity=identity)
        a2a_card = A2AAdapter.roar_to_a2a_agent_card(card)
        assert a2a_card["name"] == "minimal"
        assert a2a_card["description"] == ""
        assert a2a_card["url"] == ""
        assert a2a_card["skills"] == []


# ── Agent Card: A2A → ROAR ──────────────────────────────────────────────────


class TestA2AAgentCardToRoar:
    def test_basic_card_conversion(self, sample_a2a_agent_card):
        card_dict = A2AAdapter.a2a_agent_card_to_roar(sample_a2a_agent_card)
        assert card_dict["identity"]["display_name"] == "researcher"
        assert card_dict["description"] == "A research assistant agent"
        assert card_dict["endpoints"]["http"] == "https://researcher.example.com"
        assert card_dict["identity"]["version"] == "1.5"

    def test_skills_extracted(self, sample_a2a_agent_card):
        card_dict = A2AAdapter.a2a_agent_card_to_roar(sample_a2a_agent_card)
        assert "search" in card_dict["skills"]
        assert "cite" in card_dict["skills"]
        assert "search" in card_dict["identity"]["capabilities"]

    def test_metadata_contains_original(self, sample_a2a_agent_card):
        card_dict = A2AAdapter.a2a_agent_card_to_roar(sample_a2a_agent_card)
        assert card_dict["metadata"]["protocol"] == "a2a"
        assert card_dict["metadata"]["original"] == sample_a2a_agent_card

    def test_endpoint_override(self, sample_a2a_agent_card):
        card_dict = A2AAdapter.a2a_agent_card_to_roar(
            sample_a2a_agent_card, endpoint="https://custom.example.com"
        )
        assert card_dict["endpoints"]["http"] == "https://custom.example.com"

    def test_minimal_a2a_card(self):
        minimal = {"name": "bare-agent"}
        card_dict = A2AAdapter.a2a_agent_card_to_roar(minimal)
        assert card_dict["identity"]["display_name"] == "bare-agent"
        assert card_dict["description"] == ""
        assert card_dict["skills"] == []
        assert card_dict["identity"]["version"] == "1.0"

    def test_missing_name_defaults(self):
        card_dict = A2AAdapter.a2a_agent_card_to_roar({})
        assert card_dict["identity"]["display_name"] == "unknown-agent"

    def test_skills_with_empty_names_filtered(self):
        a2a_card = {
            "name": "agent",
            "skills": [
                {"id": "s1", "name": "valid", "description": ""},
                {"id": "s2", "name": "", "description": "empty name"},
                {"id": "s3", "description": "no name field"},
            ],
        }
        card_dict = A2AAdapter.a2a_agent_card_to_roar(a2a_card)
        assert card_dict["skills"] == ["valid"]


# ── Agent Card Round-Trip ────────────────────────────────────────────────────


class TestAgentCardRoundTrip:
    def test_roar_to_a2a_to_roar_preserves_name(self, sample_roar_agent_card):
        a2a_card = A2AAdapter.roar_to_a2a_agent_card(sample_roar_agent_card)
        back = A2AAdapter.a2a_agent_card_to_roar(a2a_card)
        assert back["identity"]["display_name"] == sample_roar_agent_card.identity.display_name

    def test_roar_to_a2a_to_roar_preserves_description(self, sample_roar_agent_card):
        a2a_card = A2AAdapter.roar_to_a2a_agent_card(sample_roar_agent_card)
        back = A2AAdapter.a2a_agent_card_to_roar(a2a_card)
        assert back["description"] == sample_roar_agent_card.description

    def test_roar_to_a2a_to_roar_preserves_url(self, sample_roar_agent_card):
        a2a_card = A2AAdapter.roar_to_a2a_agent_card(sample_roar_agent_card)
        back = A2AAdapter.a2a_agent_card_to_roar(a2a_card)
        assert back["endpoints"]["http"] == sample_roar_agent_card.endpoints.get("http", "")

    def test_a2a_to_roar_to_a2a_preserves_name(self, sample_a2a_agent_card):
        roar_dict = A2AAdapter.a2a_agent_card_to_roar(sample_a2a_agent_card)
        # Construct a real AgentCard to convert back
        identity = AgentIdentity(**roar_dict["identity"])
        card = AgentCard(
            identity=identity,
            description=roar_dict["description"],
            skills=roar_dict["skills"],
            endpoints=roar_dict["endpoints"],
        )
        back = A2AAdapter.roar_to_a2a_agent_card(card)
        assert back["name"] == sample_a2a_agent_card["name"]
        assert back["description"] == sample_a2a_agent_card["description"]


# ── Message Round-Trip ───────────────────────────────────────────────────────


class TestMessageRoundTrip:
    def test_tasks_send_round_trip(self, sample_a2a_tasks_send, orchestrator, worker):
        """tasks/send → ROAR DELEGATE → A2A submitted task preserves task_id."""
        roar_msg = A2AAdapter.a2a_to_roar(sample_a2a_tasks_send, orchestrator, worker)
        task = A2AAdapter.roar_to_a2a_task(roar_msg)
        assert task["id"] == "task-42"
        assert task["status"]["state"] == "submitted"

    def test_respond_round_trip_content(self, orchestrator, worker):
        """ROAR RESPOND → A2A completed → extract content matches."""
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"content": "The answer is 42."},
            context={"task_id": "task-1"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["artifacts"][0]["parts"][0]["text"] == "The answer is 42."


# ── Task Lifecycle ───────────────────────────────────────────────────────────


class TestTaskLifecycle:
    def test_submitted_to_working_to_completed(self, orchestrator, worker):
        """Simulate: tasks/send → working update → completed response."""
        # Step 1: tasks/send → submitted
        send_msg = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": "lifecycle-task",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Analyze data"}],
                },
            },
        }
        roar_delegate = A2AAdapter.a2a_to_roar(send_msg, orchestrator, worker)
        task_submitted = A2AAdapter.roar_to_a2a_task(roar_delegate)
        assert task_submitted["status"]["state"] == "submitted"
        assert task_submitted["id"] == "lifecycle-task"

        # Step 2: Agent reports progress → working
        roar_update = ROARMessage(
            **{"from": worker, "to": orchestrator},
            intent=MessageIntent.UPDATE,
            payload={"content": "Analyzing row 500 of 1000"},
            context={"protocol": "a2a", "task_id": "lifecycle-task"},
        )
        task_working = A2AAdapter.roar_to_a2a_task(roar_update)
        assert task_working["status"]["state"] == "working"
        assert task_working["id"] == "lifecycle-task"
        assert "Analyzing row 500" in task_working["status"]["message"]["parts"][0]["text"]

        # Step 3: Agent completes → completed with artifact
        roar_respond = ROARMessage(
            **{"from": worker, "to": orchestrator},
            intent=MessageIntent.RESPOND,
            payload={"content": "Analysis complete: 85% positive sentiment"},
            context={"protocol": "a2a", "task_id": "lifecycle-task"},
        )
        task_completed = A2AAdapter.roar_to_a2a_task(roar_respond)
        assert task_completed["status"]["state"] == "completed"
        assert task_completed["id"] == "lifecycle-task"
        assert len(task_completed["artifacts"]) == 1
        assert "85% positive" in task_completed["artifacts"][0]["parts"][0]["text"]

    def test_submitted_to_failed(self, orchestrator, worker):
        """Simulate: tasks/send → failure notification."""
        send_msg = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": "fail-task",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Do impossible thing"}],
                },
            },
        }
        roar_delegate = A2AAdapter.a2a_to_roar(send_msg, orchestrator, worker)
        task_submitted = A2AAdapter.roar_to_a2a_task(roar_delegate)
        assert task_submitted["status"]["state"] == "submitted"

        # Agent reports failure
        roar_fail = ROARMessage(
            **{"from": worker, "to": orchestrator},
            intent=MessageIntent.NOTIFY,
            payload={"event": "task.failure", "reason": "Capability not supported"},
            context={"protocol": "a2a", "task_id": "fail-task"},
        )
        task_failed = A2AAdapter.roar_to_a2a_task(roar_fail)
        assert task_failed["status"]["state"] == "failed"
        assert task_failed["id"] == "fail-task"
        assert "Capability not supported" in task_failed["status"]["message"]["parts"][0]["text"]

    def test_submitted_to_cancelled(self, orchestrator, worker):
        """Simulate: tasks/send → tasks/cancel."""
        # Submit task
        send_msg = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": "cancel-task",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "Long running task"}],
                },
            },
        }
        roar_delegate = A2AAdapter.a2a_to_roar(send_msg, orchestrator, worker)
        task_submitted = A2AAdapter.roar_to_a2a_task(roar_delegate)
        assert task_submitted["status"]["state"] == "submitted"

        # Cancel it
        cancel_msg = {
            "jsonrpc": "2.0",
            "method": "tasks/cancel",
            "id": 2,
            "params": {"id": "cancel-task"},
        }
        roar_cancel = A2AAdapter.a2a_to_roar(cancel_msg, orchestrator, worker)
        assert roar_cancel.intent == MessageIntent.NOTIFY
        assert roar_cancel.payload["event"] == "task.cancel"

        task_cancelled = A2AAdapter.roar_to_a2a_task(roar_cancel)
        assert task_cancelled["status"]["state"] == "failed"


# ── Edge Cases ───────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_non_string_content_in_respond(self, orchestrator, worker):
        """Non-string content should be stringified."""
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"content": {"nested": "data"}},
        )
        task = A2AAdapter.roar_to_a2a_task(msg, task_id="t1")
        assert isinstance(task["artifacts"][0]["parts"][0]["text"], str)

    def test_empty_task_id_in_params(self, orchestrator, worker):
        a2a = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {
                "id": "",
                "message": {"role": "user", "parts": [{"type": "text", "text": "Hi"}]},
            },
        }
        msg = A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)
        assert msg.payload["task_id"] == ""
        assert msg.intent == MessageIntent.DELEGATE

    def test_tasks_get_missing_id(self, orchestrator, worker):
        a2a = {
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "id": 1,
            "params": {},
        }
        msg = A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)
        assert msg.payload["task_id"] == ""
        assert msg.intent == MessageIntent.ASK

    def test_roar_message_id_preserved(self, orchestrator, worker):
        """Each a2a_to_roar call creates a unique ROARMessage with an id."""
        a2a = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "id": 1,
            "params": {"id": "t1", "message": {"role": "user", "parts": []}},
        }
        msg1 = A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)
        msg2 = A2AAdapter.a2a_to_roar(a2a, orchestrator, worker)
        assert msg1.id != msg2.id  # Unique message IDs

    def test_roar_to_a2a_task_with_no_context_task_id(self, orchestrator, worker):
        """Falls back to msg.id when no task_id in context."""
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"content": "result"},
            context={"protocol": "a2a"},
        )
        task = A2AAdapter.roar_to_a2a_task(msg)
        assert task["id"] == msg.id

    def test_jsonrpc_response_string_request_id(self, orchestrator, worker):
        msg = ROARMessage(
            **{"from": orchestrator, "to": worker},
            intent=MessageIntent.RESPOND,
            payload={"content": "ok"},
        )
        resp = A2AAdapter.roar_to_a2a_jsonrpc_response(msg, request_id="abc-123", task_id="t1")
        assert resp["id"] == "abc-123"
