# -*- coding: utf-8 -*-
"""ROAR gRPC Transport — high-performance bidirectional agent communication.

Provides gRPC-based transport for sending ROARMessages and streaming events.
Requires ``grpcio`` and ``grpcio-tools`` as optional dependencies::

    pip install 'roar-sdk[grpc]'

If ``grpcio`` is not installed, the module still imports but raises helpful
``ImportError`` messages when transport classes are instantiated.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterator, List, Optional

from ..types import AgentIdentity, ConnectionConfig, ROARMessage, StreamEvent

logger = logging.getLogger(__name__)

TRANSPORT_GRPC: str = "grpc"

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

_HAS_GRPC = False
try:
    import grpc  # type: ignore[import-untyped]
    _HAS_GRPC = True
except ImportError:
    grpc = None  # type: ignore[assignment]

_INSTALL_MSG = (
    "grpcio is not installed. Install with: pip install 'roar-sdk[grpc]' "
    "or: pip install grpcio grpcio-tools"
)


# ---------------------------------------------------------------------------
# Proto <-> ROAR conversion helpers
# ---------------------------------------------------------------------------


def message_to_proto_dict(msg: ROARMessage) -> Dict[str, Any]:
    """Convert a ROARMessage to a dict matching ROARMessageProto fields."""
    return {
        "roar": msg.roar,
        "id": msg.id,
        "from": {
            "did": msg.from_identity.did,
            "display_name": msg.from_identity.display_name,
            "agent_type": msg.from_identity.agent_type,
            "capabilities": list(msg.from_identity.capabilities),
            "version": msg.from_identity.version,
            "public_key": msg.from_identity.public_key or "",
        },
        "to": {
            "did": msg.to_identity.did,
            "display_name": msg.to_identity.display_name,
            "agent_type": msg.to_identity.agent_type,
            "capabilities": list(msg.to_identity.capabilities),
            "version": msg.to_identity.version,
            "public_key": msg.to_identity.public_key or "",
        },
        "intent": msg.intent,
        "payload_json": json.dumps(msg.payload, separators=(",", ":"), sort_keys=True).encode(),
        "context_json": json.dumps(msg.context, separators=(",", ":"), sort_keys=True).encode(),
        "auth": {k: str(v) for k, v in msg.auth.items()},
        "timestamp": msg.timestamp,
    }


def proto_dict_to_message(d: Dict[str, Any]) -> ROARMessage:
    """Convert a proto-style dict back to a ROARMessage."""
    from_id = d.get("from", {})
    to_id = d.get("to", {})

    return ROARMessage(
        roar=d.get("roar", "1.0"),
        id=d.get("id", ""),
        from_identity=AgentIdentity(
            did=from_id.get("did", ""),
            display_name=from_id.get("display_name", ""),
            agent_type=from_id.get("agent_type", "agent"),
            capabilities=from_id.get("capabilities", []),
            version=from_id.get("version", "1.0"),
            public_key=from_id.get("public_key") or None,
        ),
        to_identity=AgentIdentity(
            did=to_id.get("did", ""),
            display_name=to_id.get("display_name", ""),
            agent_type=to_id.get("agent_type", "agent"),
            capabilities=to_id.get("capabilities", []),
            version=to_id.get("version", "1.0"),
            public_key=to_id.get("public_key") or None,
        ),
        intent=d.get("intent", "respond"),
        payload=json.loads(d.get("payload_json", b"{}")) if d.get("payload_json") else {},
        context=json.loads(d.get("context_json", b"{}")) if d.get("context_json") else {},
        auth=d.get("auth", {}),
        timestamp=d.get("timestamp", time.time()),
    )


def stream_event_to_proto_dict(event: StreamEvent) -> Dict[str, Any]:
    """Convert a StreamEvent to a proto-style dict."""
    return {
        "type": event.type,
        "source": event.source,
        "session_id": event.session_id,
        "data_json": json.dumps(event.data, separators=(",", ":"), sort_keys=True).encode()
        if event.data
        else b"{}",
        "timestamp": event.timestamp,
        "trace_id": getattr(event, "trace_id", ""),
    }


def proto_dict_to_stream_event(d: Dict[str, Any]) -> StreamEvent:
    """Convert a proto-style dict back to a StreamEvent."""
    return StreamEvent(
        type=d.get("type", ""),
        source=d.get("source", ""),
        session_id=d.get("session_id", ""),
        data=json.loads(d.get("data_json", b"{}")) if d.get("data_json") else {},
        timestamp=d.get("timestamp", time.time()),
    )


# ---------------------------------------------------------------------------
# GRPCTransport — client-side transport
# ---------------------------------------------------------------------------


class GRPCTransport:
    """Send ROAR messages over gRPC.

    Args:
        target: gRPC server address (e.g. ``localhost:50051``).
        secure: Whether to use TLS. Defaults to False for local dev.
    """

    def __init__(self, target: str = "localhost:50051", secure: bool = False) -> None:
        if not _HAS_GRPC:
            raise ImportError(_INSTALL_MSG)
        self.target = target
        self.secure = secure
        self._channel: Any = None

    def _get_channel(self) -> Any:
        if self._channel is None:
            if self.secure:
                self._channel = grpc.secure_channel(self.target, grpc.ssl_channel_credentials())
            else:
                self._channel = grpc.insecure_channel(self.target)
        return self._channel

    async def send_message(
        self,
        config: ConnectionConfig,
        message: ROARMessage,
        signing_secret: str = "",
    ) -> ROARMessage:
        """Send a ROARMessage via gRPC and return the response."""
        channel = self._get_channel()
        # Use generic unary-unary call since we don't have generated stubs
        method = "/roar.v1.ROARService/SendMessage"
        request_data = json.dumps(message_to_proto_dict(message)).encode("utf-8")

        try:
            response = channel.unary_unary(
                method,
                request_serializer=lambda x: x,
                response_deserializer=lambda x: x,
            )(request_data)
            return proto_dict_to_message(json.loads(response))
        except Exception as exc:
            raise ConnectionError(f"gRPC send failed: {exc}") from exc

    def stream_events(
        self,
        session_id: str = "",
        event_types: Optional[List[str]] = None,
        source_dids: Optional[List[str]] = None,
    ) -> Iterator[StreamEvent]:
        """Subscribe to streaming events via gRPC server-streaming."""
        if not _HAS_GRPC:
            raise ImportError(_INSTALL_MSG)

        channel = self._get_channel()
        method = "/roar.v1.ROARService/StreamEvents"
        request = json.dumps({
            "session_id": session_id,
            "event_types": event_types or [],
            "source_dids": source_dids or [],
            "replay": False,
        }).encode("utf-8")

        try:
            response_iterator = channel.unary_stream(
                method,
                request_serializer=lambda x: x,
                response_deserializer=lambda x: x,
            )(request)
            for raw in response_iterator:
                yield proto_dict_to_stream_event(json.loads(raw))
        except Exception as exc:
            logger.error("gRPC stream failed: %s", exc)

    def health(self) -> Dict[str, Any]:
        """Check server health via gRPC."""
        channel = self._get_channel()
        method = "/roar.v1.ROARService/Health"
        try:
            response = channel.unary_unary(
                method,
                request_serializer=lambda x: x,
                response_deserializer=lambda x: x,
            )(b"{}")
            return json.loads(response)
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel is not None:
            self._channel.close()
            self._channel = None


# ---------------------------------------------------------------------------
# GRPCServicer — server-side handler (wraps ROARServer)
# ---------------------------------------------------------------------------


class GRPCServicer:
    """Wraps a ROARServer to serve via gRPC.

    This is a simplified servicer that uses JSON encoding over gRPC
    (not protobuf-compiled stubs). For production, generate stubs from
    ``spec/schemas/roar.proto`` using ``grpc_tools.protoc``.
    """

    def __init__(self, server: Any) -> None:
        if not _HAS_GRPC:
            raise ImportError(_INSTALL_MSG)
        self._server = server

    def SendMessage(self, request_bytes: bytes, context: Any) -> bytes:
        """Handle a SendMessage RPC."""
        try:
            msg_dict = json.loads(request_bytes)
            msg = proto_dict_to_message(msg_dict)
            response = self._server.handle_message(msg)
            if hasattr(response, "__await__"):
                import asyncio
                response = asyncio.get_event_loop().run_until_complete(response)
            return json.dumps(message_to_proto_dict(response)).encode("utf-8")
        except Exception as exc:
            logger.error("gRPC SendMessage error: %s", exc)
            error_resp = {
                "roar": "1.0",
                "id": "",
                "intent": "respond",
                "payload_json": json.dumps({"error": str(exc)}).encode(),
                "timestamp": time.time(),
            }
            return json.dumps(error_resp).encode("utf-8")

    def Health(self, request_bytes: bytes, context: Any) -> bytes:
        """Handle a Health RPC."""
        return json.dumps({
            "status": "ok",
            "protocol": "roar/1.0",
        }).encode("utf-8")

    def serve(self, port: int = 50051) -> None:
        """Start a gRPC server on the given port."""
        if not _HAS_GRPC:
            raise ImportError(_INSTALL_MSG)

        server = grpc.server(
            grpc.experimental.thread_pool(max_workers=10)
            if hasattr(grpc, "experimental")
            else __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(
                max_workers=10
            )
        )

        # Register generic handlers
        from grpc import GenericRpcHandler  # noqa: F401

        handlers = {
            "/roar.v1.ROARService/SendMessage": grpc.unary_unary_rpc_method_handler(
                self.SendMessage
            ),
            "/roar.v1.ROARService/Health": grpc.unary_unary_rpc_method_handler(self.Health),
        }

        class _Handler(GenericRpcHandler):
            def service(self_, handler_details):  # noqa: N805
                return handlers.get(handler_details.method)

        server.add_generic_rpc_handlers([_Handler()])
        server.add_insecure_port(f"[::]:{port}")
        server.start()
        logger.info("gRPC server started on port %d", port)
        server.wait_for_termination()
