# -*- coding: utf-8 -*-
"""Tests for the Cross-Protocol Event Streaming Bridge.

Tests cover:
  - translate_event to MCP format (task_update, tool_call, stream_end)
  - translate_event to A2A format (task_update, stream_end)
  - roar_event_to_mcp_notification round-trip
  - roar_event_to_a2a_status round-trip
  - subscribe_mcp yields MCP-formatted events
  - subscribe_a2a yields A2A-formatted events
  - subscribe_native passes through unchanged
  - Bidirectional: MCP notification -> ROAR event
  - Bidirectional: A2A status -> ROAR event
  - Unknown protocol returns ROAR native format
"""

import asyncio

import pytest

from roar_sdk.streaming import EventBus, StreamFilter, Subscription
from roar_sdk.types import StreamEvent, StreamEventType
from roar_sdk.event_bridge import (
    EventBridge,
    MCPEventSubscription,
    A2AEventSubscription,
    roar_event_to_mcp_notification,
    roar_event_to_a2a_status,
    mcp_notification_to_roar_event,
    a2a_status_to_roar_event,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def bridge(event_bus):
    return EventBridge(event_bus)


def _make_event(
    event_type: StreamEventType,
    data: dict | None = None,
    source: str = "did:roar:agent:test-001",
    session_id: str = "sess-1",
) -> StreamEvent:
    return StreamEvent(
        type=event_type,
        source=source,
        session_id=session_id,
        data=data or {},
    )


# ── translate_event to MCP format ────────────────────────────────────────────


class TestTranslateEventMCP:
    def test_task_update(self, bridge):
        event = _make_event(
            StreamEventType.TASK_UPDATE,
            data={"message": "Processing step 2", "progress": 50, "total": 100},
        )
        result = bridge.translate_event(event, "mcp")

        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "notifications/progress"
        assert result["params"]["progress"] == 50
        assert result["params"]["total"] == 100
        assert result["params"]["message"] == "Processing step 2"
        assert "id" not in result  # notifications have no id

    def test_tool_call(self, bridge):
        event = _make_event(
            StreamEventType.TOOL_CALL,
            data={"tool": "read_file", "arguments": {"path": "/tmp/x.txt"}},
        )
        result = bridge.translate_event(event, "mcp")

        assert result["method"] == "notifications/tools/list_changed"
        assert result["params"]["tool"] == "read_file"
        assert result["params"]["arguments"]["path"] == "/tmp/x.txt"

    def test_stream_start(self, bridge):
        event = _make_event(
            StreamEventType.STREAM_START,
            data={"protocol_version": "2024-11-05"},
        )
        result = bridge.translate_event(event, "mcp")

        assert result["method"] == "notifications/initialized"
        assert result["params"]["protocolVersion"] == "2024-11-05"

    def test_stream_end(self, bridge):
        event = _make_event(
            StreamEventType.STREAM_END,
            data={"reason": "all tasks completed"},
        )
        result = bridge.translate_event(event, "mcp")

        assert result["method"] == "notifications/cancelled"
        assert result["params"]["reason"] == "all tasks completed"


# ── translate_event to A2A format ────────────────────────────────────────────


class TestTranslateEventA2A:
    def test_task_update(self, bridge):
        event = _make_event(
            StreamEventType.TASK_UPDATE,
            data={"message": "Analysing input", "task_id": "t-42"},
        )
        result = bridge.translate_event(event, "a2a")

        assert result["status"]["state"] == "working"
        assert result["status"]["message"]["parts"][0]["text"] == "Analysing input"

    def test_stream_end(self, bridge):
        event = _make_event(
            StreamEventType.STREAM_END,
            data={"reason": "done", "result": "42"},
        )
        result = bridge.translate_event(event, "a2a")

        assert result["status"]["state"] == "completed"
        assert len(result["artifacts"]) == 1
        assert result["artifacts"][0]["parts"][0]["text"] == "42"

    def test_agent_delegate(self, bridge):
        event = _make_event(
            StreamEventType.AGENT_DELEGATE,
            data={"delegate_to": "did:roar:agent:specialist"},
        )
        result = bridge.translate_event(event, "a2a")

        assert result["status"]["state"] == "working"
        assert "Delegating to did:roar:agent:specialist" in result["status"]["message"]["parts"][0]["text"]

    def test_stream_start(self, bridge):
        event = _make_event(StreamEventType.STREAM_START)
        result = bridge.translate_event(event, "a2a")

        assert result["status"]["state"] == "submitted"


# ── roar_event_to_mcp_notification round-trip ────────────────────────────────


class TestMCPRoundTrip:
    def test_task_update_round_trip(self):
        original = _make_event(
            StreamEventType.TASK_UPDATE,
            data={"message": "Running tests", "progress": 75, "total": 100},
        )
        mcp = roar_event_to_mcp_notification(original)
        restored = mcp_notification_to_roar_event(mcp)

        assert restored.type == StreamEventType.TASK_UPDATE
        assert restored.data["progress"] == 75
        assert restored.data["total"] == 100
        assert restored.data["message"] == "Running tests"

    def test_tool_call_round_trip(self):
        original = _make_event(
            StreamEventType.TOOL_CALL,
            data={"tool": "run_query", "arguments": {"sql": "SELECT 1"}},
        )
        mcp = roar_event_to_mcp_notification(original)
        restored = mcp_notification_to_roar_event(mcp)

        assert restored.type == StreamEventType.TOOL_CALL
        assert restored.data["tool"] == "run_query"
        assert restored.data["arguments"]["sql"] == "SELECT 1"

    def test_stream_end_round_trip(self):
        original = _make_event(
            StreamEventType.STREAM_END,
            data={"reason": "timeout"},
        )
        mcp = roar_event_to_mcp_notification(original)
        restored = mcp_notification_to_roar_event(mcp)

        assert restored.type == StreamEventType.STREAM_END
        assert restored.data["reason"] == "timeout"

    def test_stream_start_round_trip(self):
        original = _make_event(
            StreamEventType.STREAM_START,
            data={"protocol_version": "2024-11-05", "capabilities": {"tools": True}},
        )
        mcp = roar_event_to_mcp_notification(original)
        restored = mcp_notification_to_roar_event(mcp)

        assert restored.type == StreamEventType.STREAM_START
        assert restored.data["protocol_version"] == "2024-11-05"
        assert restored.data["capabilities"]["tools"] is True


# ── roar_event_to_a2a_status round-trip ──────────────────────────────────────


class TestA2ARoundTrip:
    def test_task_update_round_trip(self):
        original = _make_event(
            StreamEventType.TASK_UPDATE,
            data={"message": "Working on it", "task_id": "task-99"},
        )
        a2a = roar_event_to_a2a_status(original, task_id="task-99")
        restored = a2a_status_to_roar_event(a2a, task_id="task-99")

        assert restored.type == StreamEventType.TASK_UPDATE
        assert restored.data["message"] == "Working on it"
        assert restored.session_id == "task-99"

    def test_stream_end_round_trip(self):
        original = _make_event(
            StreamEventType.STREAM_END,
            data={"result": "All done", "task_id": "task-7"},
        )
        a2a = roar_event_to_a2a_status(original, task_id="task-7")
        restored = a2a_status_to_roar_event(a2a, task_id="task-7")

        assert restored.type == StreamEventType.STREAM_END
        assert restored.data["result"] == "All done"

    def test_stream_start_round_trip(self):
        a2a_status = {
            "id": "task-1",
            "status": {"state": "submitted"},
        }
        restored = a2a_status_to_roar_event(a2a_status)

        assert restored.type == StreamEventType.STREAM_START
        assert restored.data["state"] == "submitted"


# ── subscribe_mcp yields MCP-formatted events ───────────────────────────────


class TestSubscribeMCP:
    @pytest.mark.asyncio
    async def test_yields_mcp_notifications(self, bridge, event_bus):
        mcp_sub = bridge.subscribe_mcp(
            StreamFilter(event_types=["task_update"])
        )

        event = _make_event(
            StreamEventType.TASK_UPDATE,
            data={"message": "Step 1", "progress": 10, "total": 50},
        )
        await event_bus.publish(event)

        result = await mcp_sub.get(timeout=2.0)
        assert result is not None
        assert result["jsonrpc"] == "2.0"
        assert result["method"] == "notifications/progress"
        assert result["params"]["progress"] == 10
        assert result["params"]["message"] == "Step 1"

        mcp_sub.close()

    @pytest.mark.asyncio
    async def test_filters_events(self, bridge, event_bus):
        mcp_sub = bridge.subscribe_mcp(
            StreamFilter(event_types=["tool_call"])
        )

        # Publish a task_update (should be filtered out)
        await event_bus.publish(
            _make_event(StreamEventType.TASK_UPDATE, data={"message": "skip me"})
        )

        # Publish a tool_call (should pass through)
        await event_bus.publish(
            _make_event(StreamEventType.TOOL_CALL, data={"tool": "grep"})
        )

        result = await mcp_sub.get(timeout=2.0)
        assert result is not None
        assert result["method"] == "notifications/tools/list_changed"
        assert result["params"]["tool"] == "grep"

        mcp_sub.close()

    @pytest.mark.asyncio
    async def test_mcp_subscription_properties(self, bridge):
        mcp_sub = bridge.subscribe_mcp()
        assert isinstance(mcp_sub, MCPEventSubscription)
        assert mcp_sub.id.startswith("sub-")
        assert not mcp_sub.closed
        mcp_sub.close()
        assert mcp_sub.closed


# ── subscribe_a2a yields A2A-formatted events ───────────────────────────────


class TestSubscribeA2A:
    @pytest.mark.asyncio
    async def test_yields_a2a_status(self, bridge, event_bus):
        a2a_sub = bridge.subscribe_a2a(
            StreamFilter(event_types=["task_update"]),
            task_id="task-100",
        )

        event = _make_event(
            StreamEventType.TASK_UPDATE,
            data={"message": "Compiling"},
        )
        await event_bus.publish(event)

        result = await a2a_sub.get(timeout=2.0)
        assert result is not None
        assert result["id"] == "task-100"
        assert result["status"]["state"] == "working"
        assert result["status"]["message"]["parts"][0]["text"] == "Compiling"

        a2a_sub.close()

    @pytest.mark.asyncio
    async def test_stream_end_yields_completed(self, bridge, event_bus):
        a2a_sub = bridge.subscribe_a2a(task_id="task-200")

        event = _make_event(
            StreamEventType.STREAM_END,
            data={"reason": "finished"},
        )
        await event_bus.publish(event)

        result = await a2a_sub.get(timeout=2.0)
        assert result is not None
        assert result["status"]["state"] == "completed"

        a2a_sub.close()

    @pytest.mark.asyncio
    async def test_a2a_subscription_properties(self, bridge):
        a2a_sub = bridge.subscribe_a2a(task_id="t-1")
        assert isinstance(a2a_sub, A2AEventSubscription)
        assert a2a_sub.id.startswith("sub-")
        assert not a2a_sub.closed
        a2a_sub.close()
        assert a2a_sub.closed


# ── subscribe_native passes through unchanged ────────────────────────────────


class TestSubscribeNative:
    @pytest.mark.asyncio
    async def test_yields_raw_stream_events(self, bridge, event_bus):
        native_sub = bridge.subscribe_native(
            StreamFilter(event_types=["tool_call"])
        )

        event = _make_event(
            StreamEventType.TOOL_CALL,
            data={"tool": "write_file", "arguments": {"path": "/tmp/out.txt"}},
        )
        await event_bus.publish(event)

        result = await native_sub.get(timeout=2.0)
        assert result is not None
        assert isinstance(result, StreamEvent)
        assert result.type == StreamEventType.TOOL_CALL
        assert result.data["tool"] == "write_file"

        native_sub.close()

    @pytest.mark.asyncio
    async def test_native_is_standard_subscription(self, bridge):
        native_sub = bridge.subscribe_native()
        assert isinstance(native_sub, Subscription)
        native_sub.close()


# ── Bidirectional: MCP notification -> ROAR event ────────────────────────────


class TestBidirectionalMCP:
    @pytest.mark.asyncio
    async def test_ingest_mcp_progress(self, bridge, event_bus):
        native_sub = bridge.subscribe_native()

        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {
                "progressToken": "tok-1",
                "progress": 30,
                "total": 100,
                "message": "Halfway there",
                "source": "did:roar:tool:external",
                "timestamp": 1700000000.0,
            },
        }

        ingested = await bridge.ingest_mcp_notification(notification)
        assert ingested.type == StreamEventType.TASK_UPDATE
        assert ingested.data["progress"] == 30
        assert ingested.source == "did:roar:tool:external"

        result = await native_sub.get(timeout=2.0)
        assert result is not None
        assert result.type == StreamEventType.TASK_UPDATE

        native_sub.close()

    @pytest.mark.asyncio
    async def test_ingest_mcp_initialized(self, bridge, event_bus):
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": True},
            },
        }

        ingested = await bridge.ingest_mcp_notification(notification)
        assert ingested.type == StreamEventType.STREAM_START
        assert ingested.data["protocol_version"] == "2024-11-05"

    @pytest.mark.asyncio
    async def test_ingest_mcp_cancelled(self, bridge, event_bus):
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"reason": "user aborted"},
        }

        ingested = await bridge.ingest_mcp_notification(notification)
        assert ingested.type == StreamEventType.STREAM_END
        assert ingested.data["reason"] == "user aborted"

    def test_standalone_mcp_to_roar(self):
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
            "params": {"tool": "search", "arguments": {"q": "hello"}},
        }
        event = mcp_notification_to_roar_event(notification)
        assert event.type == StreamEventType.TOOL_CALL
        assert event.data["tool"] == "search"


# ── Bidirectional: A2A status -> ROAR event ──────────────────────────────────


class TestBidirectionalA2A:
    @pytest.mark.asyncio
    async def test_ingest_a2a_working(self, bridge, event_bus):
        native_sub = bridge.subscribe_native()

        a2a_status = {
            "id": "task-500",
            "status": {
                "state": "working",
                "message": {
                    "role": "agent",
                    "parts": [{"type": "text", "text": "Processing data"}],
                },
            },
        }

        ingested = await bridge.ingest_a2a_status(a2a_status)
        assert ingested.type == StreamEventType.TASK_UPDATE
        assert ingested.data["message"] == "Processing data"
        assert ingested.session_id == "task-500"

        result = await native_sub.get(timeout=2.0)
        assert result is not None
        assert result.data["message"] == "Processing data"

        native_sub.close()

    @pytest.mark.asyncio
    async def test_ingest_a2a_completed(self, bridge, event_bus):
        a2a_status = {
            "id": "task-600",
            "status": {"state": "completed"},
            "artifacts": [
                {
                    "parts": [{"type": "text", "text": "Final result"}],
                }
            ],
        }

        ingested = await bridge.ingest_a2a_status(a2a_status)
        assert ingested.type == StreamEventType.STREAM_END
        assert ingested.data["result"] == "Final result"

    @pytest.mark.asyncio
    async def test_ingest_a2a_failed(self, bridge, event_bus):
        a2a_status = {
            "id": "task-700",
            "status": {"state": "failed"},
        }

        ingested = await bridge.ingest_a2a_status(a2a_status)
        assert ingested.type == StreamEventType.STREAM_END
        assert ingested.data["state"] == "failed"

    def test_standalone_a2a_to_roar(self):
        a2a_status = {
            "id": "task-800",
            "status": {"state": "working"},
        }
        event = a2a_status_to_roar_event(a2a_status)
        assert event.type == StreamEventType.TASK_UPDATE
        assert event.session_id == "task-800"

    @pytest.mark.asyncio
    async def test_ingest_a2a_with_task_id_override(self, bridge, event_bus):
        a2a_status = {
            "id": "original-id",
            "status": {"state": "working"},
        }
        ingested = await bridge.ingest_a2a_status(a2a_status, task_id="override-id")
        assert ingested.session_id == "override-id"


# ── Unknown protocol returns ROAR native format ─────────────────────────────


class TestUnknownProtocol:
    def test_unknown_returns_native(self, bridge):
        event = _make_event(
            StreamEventType.TASK_UPDATE,
            data={"message": "hello"},
        )
        result = bridge.translate_event(event, "unknown_proto")

        # Should be the raw ROAR dict
        assert result["type"] == "task_update"
        assert result["data"]["message"] == "hello"
        assert "source" in result
        assert "session_id" in result

    def test_roar_protocol_returns_native(self, bridge):
        event = _make_event(StreamEventType.TOOL_CALL, data={"tool": "ls"})
        result = bridge.translate_event(event, "roar")

        assert result["type"] == "tool_call"
        assert result["data"]["tool"] == "ls"

    def test_case_insensitive_protocol(self, bridge):
        event = _make_event(StreamEventType.TASK_UPDATE, data={"message": "hi"})

        mcp_result = bridge.translate_event(event, "MCP")
        assert mcp_result["jsonrpc"] == "2.0"

        a2a_result = bridge.translate_event(event, "A2A")
        assert "status" in a2a_result


# ── EventBridge properties and edge cases ────────────────────────────────────


class TestEventBridgeMisc:
    def test_event_bus_property(self, bridge, event_bus):
        assert bridge.event_bus is event_bus

    def test_translate_all_event_types_mcp(self, bridge):
        """Every StreamEventType can be translated to MCP without error."""
        for evt_type in StreamEventType:
            event = _make_event(evt_type)
            result = bridge.translate_event(event, "mcp")
            assert result["jsonrpc"] == "2.0"
            assert "method" in result

    def test_translate_all_event_types_a2a(self, bridge):
        """Every StreamEventType can be translated to A2A without error."""
        for evt_type in StreamEventType:
            event = _make_event(evt_type)
            result = bridge.translate_event(event, "a2a")
            assert "status" in result
            assert "state" in result["status"]
