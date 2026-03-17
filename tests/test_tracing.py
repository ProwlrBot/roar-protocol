"""Tests for message tracing and observability."""

import time
from roar_sdk.tracing import Tracer, Span, inject_trace_context, extract_trace_context


class TestTracer:
    def test_create_span(self):
        tracer = Tracer(service_name="test")
        with tracer.span("test-op") as ctx:
            ctx.set_attribute("key", "value")
        assert tracer.span_count == 1
        spans = tracer.get_recent(1)
        assert spans[0].name == "test-op"
        assert spans[0].attributes["key"] == "value"
        assert spans[0].status == "ok"
        assert spans[0].duration_ms > 0

    def test_span_error(self):
        tracer = Tracer()
        try:
            with tracer.span("failing-op") as ctx:
                raise ValueError("test error")
        except ValueError:
            pass
        spans = tracer.get_recent(1)
        assert spans[0].status == "error"
        assert spans[0].attributes["error.type"] == "ValueError"

    def test_trace_propagation(self):
        tracer = Tracer()
        tid = tracer.new_trace_id()
        with tracer.span("parent", trace_id=tid) as parent:
            with tracer.span("child", trace_id=tid, parent_span_id=parent.span.span_id):
                pass
        trace = tracer.get_trace(tid)
        assert len(trace) == 2
        assert trace[1].parent_span_id == trace[0].span_id

    def test_span_events(self):
        tracer = Tracer()
        with tracer.span("with-events") as ctx:
            ctx.add_event("checkpoint", {"step": 1})
            ctx.add_event("checkpoint", {"step": 2})
        spans = tracer.get_recent(1)
        assert len(spans[0].events) == 2

    def test_summary(self):
        tracer = Tracer(service_name="my-agent")
        with tracer.span("op1"):
            pass
        with tracer.span("op2"):
            pass
        s = tracer.summary()
        assert s["service"] == "my-agent"
        assert s["total_spans"] == 2
        assert s["error_spans"] == 0

    def test_export_and_format(self, tmp_path):
        tracer = Tracer()
        with tracer.span("exported-op") as ctx:
            ctx.set_attribute("test", True)
        path = str(tmp_path / "traces.json")
        count = tracer.export_json(path)
        assert count == 1
        import json
        with open(path) as f:
            data = json.load(f)
        assert data["span_count"] == 1
        assert len(data["traces"]) == 1

    def test_max_spans_eviction(self):
        tracer = Tracer()
        tracer._max_spans = 5
        for i in range(10):
            with tracer.span(f"op-{i}"):
                pass
        assert tracer.span_count == 5


class TestTraceContext:
    def test_inject_and_extract(self):
        ctx = {}
        inject_trace_context(ctx, "trace-abc123", "span-def456")
        tid, sid = extract_trace_context(ctx)
        assert tid == "trace-abc123"
        assert sid == "span-def456"

    def test_extract_missing(self):
        tid, sid = extract_trace_context({})
        assert tid == ""
        assert sid == ""
