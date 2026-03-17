# -*- coding: utf-8 -*-
"""ROAR Protocol — OpenTelemetry-compatible tracing bridge.

Converts ROAR's native Span/Tracer objects to OTLP-compatible JSON dicts
that can be sent to any OpenTelemetry collector via HTTP.  This module has
**zero** hard dependencies beyond the standard library — ``httpx`` is used
opportunistically for the HTTP export but is not required.

Usage::

    from roar_sdk.tracing import Tracer
    from roar_sdk.otel import OTLPExporter, instrument_message

    tracer = Tracer(service_name="my-agent")

    # Auto-instrument a single message
    ctx = instrument_message(msg, tracer)

    # Export collected spans to a local OTLP collector
    exporter = OTLPExporter(endpoint="http://localhost:4318/v1/traces")
    count = exporter.export(tracer)
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List

from .tracing import Span, SpanContext, Tracer, extract_trace_context, inject_trace_context
from .types import ROARMessage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NANOS_PER_SEC = 1_000_000_000


def _time_to_nanos(t: float) -> int:
    """Convert a Unix timestamp (seconds, float) to nanoseconds (int)."""
    return int(t * _NANOS_PER_SEC)


def _hex_id(raw: str, length: int = 32) -> str:
    """Normalise a ROAR id to a zero-padded hex string of *length* chars.

    ROAR trace/span ids look like ``trace-ab01…`` or ``span-cd02…``.  OTLP
    expects fixed-length lowercase hex (32 chars for trace, 16 for span).
    We strip the prefix, keep up to *length* hex chars, and left-pad with
    zeroes.
    """
    # Strip known prefixes
    for prefix in ("trace-", "span-"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    # Keep only hex characters
    hex_chars = "".join(c for c in raw if c in "0123456789abcdef")
    return hex_chars[:length].ljust(length, "0")


# ---------------------------------------------------------------------------
# Single-span conversion
# ---------------------------------------------------------------------------


def roar_span_to_otlp(span: Span, service_name: str = "roar-agent") -> Dict[str, Any]:
    """Convert a single ROAR ``Span`` to an OTLP-compatible JSON dict.

    The returned dict follows the `OTLP/HTTP JSON`_ structure for a single
    span inside a ``ScopeSpans`` resource.

    .. _OTLP/HTTP JSON:
       https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding
    """
    trace_id = _hex_id(span.trace_id, 32)
    span_id = _hex_id(span.span_id, 16)
    parent_span_id = _hex_id(span.parent_span_id, 16) if span.parent_span_id else ""

    # Map ROAR attributes → OTLP key/value tags
    tags: List[Dict[str, Any]] = []
    for key, value in span.attributes.items():
        tags.append(_kv(key, value))

    # Always include service.name
    tags.append(_kv("service.name", service_name))

    # Map ROAR events → OTLP log records
    logs: List[Dict[str, Any]] = []
    for ev in span.events:
        log_entry: Dict[str, Any] = {
            "timeUnixNano": _time_to_nanos(ev.get("timestamp", 0)),
            "name": ev.get("name", ""),
        }
        if ev.get("attributes"):
            log_entry["attributes"] = [_kv(k, v) for k, v in ev["attributes"].items()]
        logs.append(log_entry)

    # OTLP status code: 0 = UNSET, 1 = OK, 2 = ERROR
    if span.status == "error":
        status = {"code": 2, "message": span.attributes.get("error.message", "")}
    else:
        status = {"code": 1, "message": ""}

    start_nanos = _time_to_nanos(span.start_time)
    end_nanos = _time_to_nanos(span.end_time) if span.end_time > 0 else start_nanos

    return {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": parent_span_id,
        "operationName": span.name,
        "startTimeUnixNano": start_nanos,
        "endTimeUnixNano": end_nanos,
        "durationNano": end_nanos - start_nanos,
        "tags": tags,
        "logs": logs,
        "status": status,
    }


def _kv(key: str, value: Any) -> Dict[str, Any]:
    """Build an OTLP ``KeyValue`` attribute entry."""
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": value}}
    if isinstance(value, float):
        return {"key": key, "value": {"intValue": int(value)} if value == int(value) else {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


# ---------------------------------------------------------------------------
# ROARSpanExporter — batch conversion
# ---------------------------------------------------------------------------


class ROARSpanExporter:
    """Converts a list of ROAR ``Span`` objects to OTLP-compatible dicts.

    This class does **not** perform any I/O — it only transforms data.
    """

    def __init__(self, service_name: str = "roar-agent") -> None:
        self.service_name = service_name

    def export_spans(self, spans: List[Span]) -> List[Dict[str, Any]]:
        """Convert *spans* to a list of OTLP-compatible span dicts."""
        return [roar_span_to_otlp(s, self.service_name) for s in spans]


# ---------------------------------------------------------------------------
# OTLPExporter — HTTP export to any OTLP collector
# ---------------------------------------------------------------------------


class OTLPExporter:
    """Send ROAR spans to an OTLP/HTTP collector endpoint.

    Uses ``httpx`` if available; otherwise logs a warning and returns 0.
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:4318/v1/traces",
        service_name: str = "roar-agent",
    ) -> None:
        self.endpoint = endpoint
        self.service_name = service_name
        self._span_exporter = ROARSpanExporter(service_name=service_name)

    def _build_otlp_payload(self, otlp_spans: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Wrap span dicts in the full OTLP ``ExportTraceServiceRequest`` envelope."""
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            _kv("service.name", self.service_name),
                        ],
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "roar-sdk", "version": "1.0"},
                            "spans": otlp_spans,
                        },
                    ],
                },
            ],
        }

    def export(self, tracer: Tracer) -> int:
        """Export all spans currently held by *tracer*.

        Returns the number of spans sent, or 0 if the export failed.
        """
        spans = tracer.get_recent(tracer.span_count)
        if not spans:
            return 0

        otlp_spans = self._span_exporter.export_spans(spans)
        payload = self._build_otlp_payload(otlp_spans)

        try:
            import httpx  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "httpx is not installed — cannot send spans to %s. "
                "Install with: pip install httpx",
                self.endpoint,
            )
            return 0

        try:
            response = httpx.post(
                self.endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Exported %d spans to %s", len(otlp_spans), self.endpoint)
            return len(otlp_spans)
        except Exception as exc:
            logger.error("Failed to export spans to %s: %s", self.endpoint, exc)
            return 0

    def build_payload(self, tracer: Tracer) -> Dict[str, Any]:
        """Build the OTLP payload dict without sending it.

        Useful for debugging or when you want to send the payload yourself.
        """
        spans = tracer.get_recent(tracer.span_count)
        otlp_spans = self._span_exporter.export_spans(spans)
        return self._build_otlp_payload(otlp_spans)


# ---------------------------------------------------------------------------
# instrument_message — single-message instrumentation
# ---------------------------------------------------------------------------


def instrument_message(msg: ROARMessage, tracer: Tracer) -> SpanContext:
    """Create a span for a single ROAR message and propagate trace context.

    Extracts ``trace_id`` / ``parent_span_id`` from ``msg.context`` (if present)
    and creates a child span.  The trace context is then injected back into
    ``msg.context`` so downstream agents can continue the trace.

    Returns a ``SpanContext`` that the caller should use as a context manager::

        ctx = instrument_message(msg, tracer)
        with ctx:
            response = await handle(msg)
    """
    trace_id, parent_span_id = extract_trace_context(msg.context)
    if not trace_id:
        trace_id = tracer.new_trace_id()

    ctx = tracer.span(
        name=f"message.{msg.intent}",
        trace_id=trace_id,
        parent_span_id=parent_span_id,
    )

    # Attach useful attributes
    ctx.set_attribute("from_did", msg.from_identity.did)
    ctx.set_attribute("to_did", msg.to_identity.did)
    ctx.set_attribute("intent", str(msg.intent))
    ctx.set_attribute("message_id", msg.id)

    # Propagate trace context into the message for downstream agents
    inject_trace_context(msg.context, trace_id, ctx.span.span_id)

    return ctx


# ---------------------------------------------------------------------------
# instrument_server — monkey-patch ROARServer.handle_message
# ---------------------------------------------------------------------------


def instrument_server(server: Any, tracer: Tracer) -> None:
    """Monkey-patch a ``ROARServer`` so every message is auto-traced.

    Wraps ``server.handle_message`` to create a span for each incoming
    message.  The span records ``from_did``, ``to_did``, ``intent``,
    ``message_id``, and ``duration``.

    Parameters
    ----------
    server:
        A ``ROARServer`` instance (imported as ``Any`` to avoid a circular
        import at module level).
    tracer:
        The ``Tracer`` that will collect the spans.
    """
    original_handle = server.handle_message

    if inspect.iscoroutinefunction(original_handle):
        async def traced_handle(msg: ROARMessage) -> ROARMessage:
            ctx = instrument_message(msg, tracer)
            try:
                response = await original_handle(msg)
                ctx.set_attribute("response_intent", str(response.intent))
                if "error" in response.payload:
                    ctx.span.set_attribute("error.type", response.payload["error"])
                    ctx.span.set_attribute("error.message", response.payload.get("message", ""))
                    ctx.span.end(status="error")
                else:
                    ctx.span.end(status="ok")
                return response
            except Exception:
                ctx.span.end(status="error")
                raise

        server.handle_message = traced_handle  # type: ignore[assignment]
    else:
        def traced_handle_sync(msg: ROARMessage) -> ROARMessage:
            ctx = instrument_message(msg, tracer)
            try:
                response = original_handle(msg)
                ctx.set_attribute("response_intent", str(response.intent))
                if "error" in response.payload:
                    ctx.span.set_attribute("error.type", response.payload["error"])
                    ctx.span.set_attribute("error.message", response.payload.get("message", ""))
                    ctx.span.end(status="error")
                else:
                    ctx.span.end(status="ok")
                return response
            except Exception:
                ctx.span.end(status="error")
                raise

        server.handle_message = traced_handle_sync  # type: ignore[assignment]

    logger.info("Instrumented ROARServer '%s' with tracing", getattr(server, '_identity', 'unknown'))
