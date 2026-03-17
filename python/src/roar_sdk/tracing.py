# -*- coding: utf-8 -*-
"""ROAR Protocol — Message tracing and observability (Layer 5).

Provides distributed tracing for agent interactions. Each message exchange
gets a trace_id (propagated in context), and spans track timing across
agent hops. Traces can be exported to JSON, logged, or sent to collectors.

Usage::

    from roar_sdk.tracing import Tracer, Span

    tracer = Tracer()
    with tracer.span("handle-delegate", trace_id=msg.context.get("trace_id")) as span:
        span.set_attribute("from", msg.from_identity.did)
        span.set_attribute("intent", msg.intent)
        response = await handle(msg)
        span.set_attribute("status", "ok")

    # Export all traces
    tracer.export_json("traces.json")
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single traced operation within a message exchange."""
    trace_id: str
    span_id: str
    name: str
    start_time: float
    end_time: float = 0.0
    parent_span_id: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "ok"

    @property
    def duration_ms(self) -> float:
        if self.end_time <= 0:
            return 0.0
        return (self.end_time - self.start_time) * 1000

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def end(self, status: str = "ok") -> None:
        self.end_time = time.time()
        self.status = status

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


class SpanContext:
    """Context manager for auto-ending spans."""

    def __init__(self, span: Span) -> None:
        self._span = span

    @property
    def span(self) -> Span:
        return self._span

    def set_attribute(self, key: str, value: Any) -> None:
        self._span.set_attribute(key, value)

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None) -> None:
        self._span.add_event(name, attributes)

    def __enter__(self) -> SpanContext:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self._span.set_attribute("error.type", exc_type.__name__)
            self._span.set_attribute("error.message", str(exc_val))
            self._span.end(status="error")
        else:
            self._span.end(status="ok")


class Tracer:
    """Collects spans into traces for observability.

    Thread-safe for single-writer scenarios (typical in async agent code).
    """

    def __init__(self, service_name: str = "roar-agent") -> None:
        self.service_name = service_name
        self._spans: List[Span] = []
        self._max_spans = 10_000

    @property
    def span_count(self) -> int:
        return len(self._spans)

    def new_trace_id(self) -> str:
        return f"trace-{uuid.uuid4().hex[:16]}"

    def span(
        self,
        name: str,
        trace_id: Optional[str] = None,
        parent_span_id: str = "",
    ) -> SpanContext:
        """Create a new span. Use as a context manager."""
        tid = trace_id or self.new_trace_id()
        s = Span(
            trace_id=tid,
            span_id=f"span-{uuid.uuid4().hex[:12]}",
            name=name,
            start_time=time.time(),
            parent_span_id=parent_span_id,
        )
        self._spans.append(s)
        if len(self._spans) > self._max_spans:
            self._spans = self._spans[-self._max_spans:]
        return SpanContext(s)

    def get_trace(self, trace_id: str) -> List[Span]:
        """Get all spans for a given trace."""
        return [s for s in self._spans if s.trace_id == trace_id]

    def get_recent(self, limit: int = 50) -> List[Span]:
        """Get the most recent spans."""
        return list(reversed(self._spans[-limit:]))

    def export_json(self, path: str) -> int:
        """Export all traces to a JSON file. Returns span count."""
        traces: Dict[str, List[Dict[str, Any]]] = {}
        for s in self._spans:
            traces.setdefault(s.trace_id, []).append(s.to_dict())
        with open(path, "w") as f:
            json.dump({
                "service": self.service_name,
                "exported_at": time.time(),
                "trace_count": len(traces),
                "span_count": len(self._spans),
                "traces": traces,
            }, f, indent=2)
        return len(self._spans)

    def summary(self) -> Dict[str, Any]:
        """Get a summary of tracing activity."""
        traces = set(s.trace_id for s in self._spans)
        errors = sum(1 for s in self._spans if s.status == "error")
        durations = [s.duration_ms for s in self._spans if s.end_time > 0]
        return {
            "service": self.service_name,
            "total_spans": len(self._spans),
            "total_traces": len(traces),
            "error_spans": errors,
            "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0,
            "max_duration_ms": round(max(durations), 2) if durations else 0,
        }


def inject_trace_context(context: Dict[str, Any], trace_id: str, span_id: str = "") -> Dict[str, Any]:
    """Inject trace context into a ROARMessage context dict for propagation."""
    context["trace_id"] = trace_id
    if span_id:
        context["parent_span_id"] = span_id
    return context


def extract_trace_context(context: Dict[str, Any]) -> tuple[str, str]:
    """Extract trace_id and parent_span_id from a ROARMessage context."""
    return context.get("trace_id", ""), context.get("parent_span_id", "")
