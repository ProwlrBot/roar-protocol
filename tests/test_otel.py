"""Tests for ROAR → OTLP tracing bridge."""

import sys
import time
import types
from unittest.mock import patch

from roar_sdk.otel import (
    OTLPExporter,
    ROARSpanExporter,
    instrument_message,
    instrument_server,
    roar_span_to_otlp,
    _hex_id,
    _kv,
    _NANOS_PER_SEC,
)
from roar_sdk.tracing import Span, SpanContext, Tracer
from roar_sdk.types import AgentIdentity, MessageIntent, ROARMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_msg(
    intent: MessageIntent = MessageIntent.DELEGATE,
    context: dict | None = None,
) -> ROARMessage:
    """Build a minimal ROARMessage for testing."""
    return ROARMessage(
        **{
            "from": AgentIdentity(display_name="alice"),
            "to": AgentIdentity(display_name="bob"),
        },
        intent=intent,
        payload={"task": "summarise"},
        context=context or {},
    )


def _make_span(
    name: str = "test-op",
    status: str = "ok",
    attributes: dict | None = None,
    events: list | None = None,
    parent_span_id: str = "",
) -> Span:
    """Build a finished Span for testing."""
    s = Span(
        trace_id="trace-aabbccdd11223344",
        span_id="span-112233aabb",
        name=name,
        start_time=1700000000.0,
        end_time=1700000001.5,
        parent_span_id=parent_span_id,
        status=status,
        attributes=attributes or {},
        events=events or [],
    )
    return s


# ---------------------------------------------------------------------------
# roar_span_to_otlp — single-span conversion
# ---------------------------------------------------------------------------


class TestRoarSpanToOtlp:
    def test_basic_fields(self):
        span = _make_span()
        d = roar_span_to_otlp(span, service_name="test-svc")

        assert d["traceId"] == "aabbccdd11223344".ljust(32, "0")
        assert d["spanId"] == "112233aabb000000"
        assert d["parentSpanId"] == ""
        assert d["operationName"] == "test-op"
        assert isinstance(d["startTimeUnixNano"], int)
        assert isinstance(d["endTimeUnixNano"], int)
        assert d["durationNano"] == d["endTimeUnixNano"] - d["startTimeUnixNano"]
        assert d["durationNano"] > 0

    def test_timestamps_nanoseconds(self):
        span = _make_span()
        d = roar_span_to_otlp(span)

        assert d["startTimeUnixNano"] == int(1700000000.0 * _NANOS_PER_SEC)
        assert d["endTimeUnixNano"] == int(1700000001.5 * _NANOS_PER_SEC)

    def test_parent_span_id_present(self):
        span = _make_span(parent_span_id="span-deadbeef")
        d = roar_span_to_otlp(span)
        assert d["parentSpanId"] == "deadbeef00000000"

    def test_attributes_as_tags(self):
        span = _make_span(attributes={"from_did": "did:roar:agent:alice", "count": 42})
        d = roar_span_to_otlp(span)

        tag_keys = {t["key"] for t in d["tags"]}
        assert "from_did" in tag_keys
        assert "count" in tag_keys
        assert "service.name" in tag_keys

    def test_events_as_logs(self):
        events = [
            {"name": "checkpoint", "timestamp": 1700000000.5, "attributes": {"step": 1}},
            {"name": "done", "timestamp": 1700000001.0, "attributes": {}},
        ]
        span = _make_span(events=events)
        d = roar_span_to_otlp(span)

        assert len(d["logs"]) == 2
        assert d["logs"][0]["name"] == "checkpoint"
        assert d["logs"][0]["timeUnixNano"] == int(1700000000.5 * _NANOS_PER_SEC)
        assert any(a["key"] == "step" for a in d["logs"][0].get("attributes", []))

    def test_ok_status(self):
        span = _make_span(status="ok")
        d = roar_span_to_otlp(span)
        assert d["status"]["code"] == 1

    def test_error_status(self):
        span = _make_span(
            status="error",
            attributes={"error.type": "ValueError", "error.message": "bad input"},
        )
        d = roar_span_to_otlp(span)
        assert d["status"]["code"] == 2
        assert d["status"]["message"] == "bad input"

    def test_error_tags_present(self):
        span = _make_span(
            status="error",
            attributes={"error.type": "TimeoutError", "error.message": "timed out"},
        )
        d = roar_span_to_otlp(span)
        tag_keys = {t["key"] for t in d["tags"]}
        assert "error.type" in tag_keys
        assert "error.message" in tag_keys

    def test_unfinished_span(self):
        """A span with end_time=0 should still produce a valid dict."""
        span = _make_span()
        span.end_time = 0.0
        d = roar_span_to_otlp(span)
        assert d["endTimeUnixNano"] == d["startTimeUnixNano"]
        assert d["durationNano"] == 0


# ---------------------------------------------------------------------------
# ROARSpanExporter — batch conversion
# ---------------------------------------------------------------------------


class TestROARSpanExporter:
    def test_export_multiple_spans(self):
        exporter = ROARSpanExporter(service_name="batch-svc")
        spans = [_make_span(name=f"op-{i}") for i in range(5)]
        result = exporter.export_spans(spans)

        assert len(result) == 5
        for i, d in enumerate(result):
            assert d["operationName"] == f"op-{i}"

    def test_empty_list(self):
        exporter = ROARSpanExporter()
        assert exporter.export_spans([]) == []

    def test_service_name_propagated(self):
        exporter = ROARSpanExporter(service_name="custom-svc")
        result = exporter.export_spans([_make_span()])
        svc_tags = [t for t in result[0]["tags"] if t["key"] == "service.name"]
        assert len(svc_tags) == 1
        assert svc_tags[0]["value"]["stringValue"] == "custom-svc"


# ---------------------------------------------------------------------------
# OTLPExporter — payload structure and graceful fallback
# ---------------------------------------------------------------------------


class TestOTLPExporter:
    def test_build_payload_structure(self):
        tracer = Tracer(service_name="test-agent")
        with tracer.span("op-a"):
            pass
        with tracer.span("op-b"):
            pass

        exporter = OTLPExporter(service_name="test-agent")
        payload = exporter.build_payload(tracer)

        # Top-level OTLP envelope
        assert "resourceSpans" in payload
        rs = payload["resourceSpans"]
        assert len(rs) == 1

        # Resource attributes
        res_attrs = rs[0]["resource"]["attributes"]
        svc = [a for a in res_attrs if a["key"] == "service.name"]
        assert svc[0]["value"]["stringValue"] == "test-agent"

        # ScopeSpans
        ss = rs[0]["scopeSpans"]
        assert len(ss) == 1
        assert ss[0]["scope"]["name"] == "roar-sdk"
        assert len(ss[0]["spans"]) == 2

    def test_export_without_httpx(self):
        """export() returns 0 and logs a warning when httpx is missing."""
        tracer = Tracer()
        with tracer.span("some-op"):
            pass

        exporter = OTLPExporter()

        # Simulate httpx not being installed
        with patch.dict(sys.modules, {"httpx": None}):
            count = exporter.export(tracer)
        assert count == 0

    def test_export_empty_tracer(self):
        tracer = Tracer()
        exporter = OTLPExporter()
        assert exporter.export(tracer) == 0

    def test_build_payload_empty(self):
        tracer = Tracer()
        exporter = OTLPExporter()
        payload = exporter.build_payload(tracer)
        assert payload["resourceSpans"][0]["scopeSpans"][0]["spans"] == []


# ---------------------------------------------------------------------------
# instrument_message — trace context propagation
# ---------------------------------------------------------------------------


class TestInstrumentMessage:
    def test_creates_span(self):
        tracer = Tracer()
        msg = _make_msg()
        ctx = instrument_message(msg, tracer)
        with ctx:
            pass

        assert tracer.span_count == 1
        span = tracer.get_recent(1)[0]
        assert span.name == "message.delegate"
        assert span.attributes["from_did"] == msg.from_identity.did
        assert span.attributes["to_did"] == msg.to_identity.did
        assert span.attributes["intent"] == "delegate"
        assert span.attributes["message_id"] == msg.id

    def test_propagates_existing_trace_id(self):
        tracer = Tracer()
        msg = _make_msg(context={"trace_id": "trace-existing123", "parent_span_id": "span-parent456"})
        ctx = instrument_message(msg, tracer)
        with ctx:
            pass

        span = tracer.get_recent(1)[0]
        assert span.trace_id == "trace-existing123"
        assert span.parent_span_id == "span-parent456"

    def test_generates_trace_id_when_missing(self):
        tracer = Tracer()
        msg = _make_msg(context={})
        ctx = instrument_message(msg, tracer)
        with ctx:
            pass

        span = tracer.get_recent(1)[0]
        assert span.trace_id.startswith("trace-")

    def test_injects_context_back_into_message(self):
        tracer = Tracer()
        msg = _make_msg(context={})
        ctx = instrument_message(msg, tracer)
        with ctx:
            pass

        # After instrumentation, msg.context should have trace_id and parent_span_id
        assert "trace_id" in msg.context
        assert "parent_span_id" in msg.context
        assert msg.context["parent_span_id"] == tracer.get_recent(1)[0].span_id

    def test_error_during_handling(self):
        tracer = Tracer()
        msg = _make_msg()
        ctx = instrument_message(msg, tracer)
        try:
            with ctx:
                raise RuntimeError("handler crashed")
        except RuntimeError:
            pass

        span = tracer.get_recent(1)[0]
        assert span.status == "error"
        assert span.attributes["error.type"] == "RuntimeError"
        assert "handler crashed" in span.attributes["error.message"]

    def test_otlp_conversion_of_instrumented_span(self):
        """End-to-end: instrument → convert → verify OTLP dict."""
        tracer = Tracer()
        msg = _make_msg()
        with instrument_message(msg, tracer):
            pass

        span = tracer.get_recent(1)[0]
        d = roar_span_to_otlp(span, service_name="e2e-test")

        assert d["operationName"] == "message.delegate"
        assert d["status"]["code"] == 1
        assert d["durationNano"] >= 0
        tag_keys = {t["key"] for t in d["tags"]}
        assert "from_did" in tag_keys
        assert "to_did" in tag_keys
        assert "intent" in tag_keys


# ---------------------------------------------------------------------------
# instrument_server — monkey-patching
# ---------------------------------------------------------------------------


class TestInstrumentServer:
    def test_patches_handle_message(self):
        """instrument_server wraps handle_message and records spans."""
        tracer = Tracer()

        # Minimal mock server with an async handle_message
        class FakeServer:
            _identity = AgentIdentity(display_name="test-server")

            async def handle_message(self, msg: ROARMessage) -> ROARMessage:
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"status": "ok"},
                )

        server = FakeServer()
        instrument_server(server, tracer)

        # Run the patched handler
        import asyncio
        msg = _make_msg()
        response = asyncio.get_event_loop().run_until_complete(server.handle_message(msg))

        assert response.intent == MessageIntent.RESPOND
        assert tracer.span_count == 1
        span = tracer.get_recent(1)[0]
        assert span.attributes["intent"] == "delegate"
        assert span.attributes["response_intent"] == "respond"
        assert span.status == "ok"

    def test_patches_sync_handle_message(self):
        tracer = Tracer()

        class FakeSyncServer:
            _identity = AgentIdentity(display_name="sync-server")

            def handle_message(self, msg: ROARMessage) -> ROARMessage:
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"status": "done"},
                )

        server = FakeSyncServer()
        instrument_server(server, tracer)

        msg = _make_msg()
        response = server.handle_message(msg)

        assert response.intent == MessageIntent.RESPOND
        assert tracer.span_count == 1

    def test_error_response_marks_span_error(self):
        tracer = Tracer()

        class FakeServer:
            _identity = AgentIdentity(display_name="err-server")

            async def handle_message(self, msg: ROARMessage) -> ROARMessage:
                return ROARMessage(
                    **{"from": self._identity, "to": msg.from_identity},
                    intent=MessageIntent.RESPOND,
                    payload={"error": "unhandled_intent", "message": "No handler"},
                )

        server = FakeServer()
        instrument_server(server, tracer)

        import asyncio
        msg = _make_msg()
        asyncio.get_event_loop().run_until_complete(server.handle_message(msg))

        span = tracer.get_recent(1)[0]
        assert span.status == "error"
        assert span.attributes["error.type"] == "unhandled_intent"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_hex_id_strips_prefix(self):
        assert _hex_id("trace-aabb", 32) == "aabb" + "0" * 28
        assert _hex_id("span-1234ab", 16) == "1234ab" + "0" * 10

    def test_hex_id_no_prefix(self):
        assert _hex_id("deadbeef", 16) == "deadbeef00000000"

    def test_hex_id_truncates(self):
        long_hex = "a" * 40
        assert len(_hex_id(long_hex, 32)) == 32

    def test_kv_string(self):
        result = _kv("name", "alice")
        assert result == {"key": "name", "value": {"stringValue": "alice"}}

    def test_kv_int(self):
        result = _kv("count", 42)
        assert result == {"key": "count", "value": {"intValue": 42}}

    def test_kv_bool(self):
        result = _kv("enabled", True)
        assert result == {"key": "enabled", "value": {"boolValue": True}}

    def test_kv_float(self):
        result = _kv("ratio", 3.14)
        assert result == {"key": "ratio", "value": {"doubleValue": 3.14}}

    def test_kv_float_whole_number(self):
        """A float like 5.0 should become intValue."""
        result = _kv("count", 5.0)
        assert result == {"key": "count", "value": {"intValue": 5}}
