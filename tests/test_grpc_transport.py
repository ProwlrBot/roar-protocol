# -*- coding: utf-8 -*-
"""Tests for the gRPC transport module — all mocked, no grpcio required."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from roar_sdk.types import AgentIdentity, ROARMessage, StreamEvent


# ---------------------------------------------------------------------------
# Conversion tests (no grpcio needed)
# ---------------------------------------------------------------------------


class TestProtoConversion:
    """Test message ↔ proto-dict conversion helpers."""

    def _make_msg(self) -> ROARMessage:
        alice = AgentIdentity(
            did="did:roar:agent:alice-0001",
            display_name="Alice",
        )
        bob = AgentIdentity(
            did="did:roar:agent:bob-0002",
            display_name="Bob",
        )
        return ROARMessage(
            from_identity=alice,
            to_identity=bob,
            intent="ask",
            payload={"question": "Hello?"},
        )

    def test_message_to_proto_dict(self) -> None:
        from roar_sdk.transports.grpc import message_to_proto_dict

        msg = self._make_msg()
        d = message_to_proto_dict(msg)
        assert d["roar"] == "1.0"
        assert d["intent"] == "ask"
        assert d["from"]["did"] == "did:roar:agent:alice-0001"
        assert d["to"]["did"] == "did:roar:agent:bob-0002"
        assert isinstance(d["payload_json"], bytes)
        payload = json.loads(d["payload_json"])
        assert payload["question"] == "Hello?"

    def test_proto_dict_to_message(self) -> None:
        from roar_sdk.transports.grpc import message_to_proto_dict, proto_dict_to_message

        msg = self._make_msg()
        d = message_to_proto_dict(msg)
        restored = proto_dict_to_message(d)
        assert restored.from_identity.did == msg.from_identity.did
        assert restored.to_identity.did == msg.to_identity.did
        assert restored.intent == msg.intent
        assert restored.payload == msg.payload

    def test_roundtrip_preserves_fields(self) -> None:
        from roar_sdk.transports.grpc import message_to_proto_dict, proto_dict_to_message

        msg = self._make_msg()
        d = message_to_proto_dict(msg)
        restored = proto_dict_to_message(d)
        d2 = message_to_proto_dict(restored)
        assert d["roar"] == d2["roar"]
        assert d["intent"] == d2["intent"]
        assert json.loads(d["payload_json"]) == json.loads(d2["payload_json"])

    def test_stream_event_conversion(self) -> None:
        from roar_sdk.transports.grpc import (
            proto_dict_to_stream_event,
            stream_event_to_proto_dict,
        )

        event = StreamEvent(
            type="task_update",
            source="did:roar:agent:test",
            session_id="sess-1",
            data={"progress": 0.75},
        )
        d = stream_event_to_proto_dict(event)
        assert d["type"] == "task_update"
        assert isinstance(d["data_json"], bytes)

        restored = proto_dict_to_stream_event(d)
        assert restored.type == event.type
        assert restored.source == event.source
        assert restored.data["progress"] == 0.75


# ---------------------------------------------------------------------------
# Transport tests (mocked grpcio)
# ---------------------------------------------------------------------------


class TestGRPCTransport:
    """Test GRPCTransport with mocked gRPC channels."""

    @patch.dict("sys.modules", {"grpc": MagicMock()})
    def test_graceful_import_without_grpcio(self) -> None:
        """Module imports cleanly even without grpcio."""
        # The module should import — _HAS_GRPC will be checked at instantiation
        from roar_sdk.transports import grpc as grpc_mod

        assert hasattr(grpc_mod, "GRPCTransport")
        assert hasattr(grpc_mod, "GRPCServicer")
        assert hasattr(grpc_mod, "TRANSPORT_GRPC")

    def test_transport_type_constant(self) -> None:
        from roar_sdk.transports.grpc import TRANSPORT_GRPC

        assert TRANSPORT_GRPC == "grpc"


class TestGRPCServicer:
    """Test GRPCServicer message handling."""

    def test_health_response(self) -> None:
        from roar_sdk.transports.grpc import GRPCServicer, _HAS_GRPC

        if not _HAS_GRPC:
            pytest.skip("grpcio not installed")

        mock_server = MagicMock()
        servicer = GRPCServicer(mock_server)
        result = servicer.Health(b"{}", None)
        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["protocol"] == "roar/1.0"
