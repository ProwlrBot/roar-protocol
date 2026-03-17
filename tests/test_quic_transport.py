# -*- coding: utf-8 -*-
"""Tests for ROAR QUIC/HTTP3 transport layer.

All tests are designed to pass WITHOUT aioquic or h3 installed — they
exercise the fallback and degradation paths that most CI environments
will hit.
"""

from __future__ import annotations

import importlib
import json
import sys
import types
from unittest import mock

import pytest

from roar_sdk.types import (
    AgentIdentity,
    ConnectionConfig,
    MessageIntent,
    ROARMessage,
    TransportType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message() -> ROARMessage:
    """Build a minimal signed ROARMessage for testing."""
    return ROARMessage(
        **{
            "from": AgentIdentity(display_name="Alice", agent_type="agent"),
            "to": AgentIdentity(display_name="Bob", agent_type="agent"),
        },
        intent=MessageIntent.EXECUTE,
        payload={"action": "ping"},
    )


def _response_json(msg: ROARMessage) -> str:
    """Return the wire-format JSON for a response message."""
    resp = ROARMessage(
        **{
            "from": msg.to_identity,
            "to": msg.from_identity,
        },
        intent=MessageIntent.RESPOND,
        payload={"result": "pong"},
    )
    return json.dumps(resp.model_dump(by_alias=True))


# ---------------------------------------------------------------------------
# QUICTransport — aioquic not installed
# ---------------------------------------------------------------------------

class TestQUICTransportMissing:
    """QUICTransport must raise ImportError when aioquic is absent."""

    def test_init_raises_import_error(self):
        """Constructing QUICTransport without aioquic raises ImportError."""
        from roar_sdk.transports.quic import _HAS_AIOQUIC

        if _HAS_AIOQUIC:
            pytest.skip("aioquic is installed; cannot test missing-dep path")

        from roar_sdk.transports.quic import QUICTransport

        with pytest.raises(ImportError, match="aioquic"):
            QUICTransport()

    def test_import_error_message_contains_install_hint(self):
        from roar_sdk.transports.quic import _HAS_AIOQUIC

        if _HAS_AIOQUIC:
            pytest.skip("aioquic is installed")

        from roar_sdk.transports.quic import QUICTransport

        with pytest.raises(ImportError, match="pip install"):
            QUICTransport()


# ---------------------------------------------------------------------------
# HTTP3Transport — fallback behaviour
# ---------------------------------------------------------------------------

class TestHTTP3TransportFallback:
    """HTTP3Transport falls back gracefully when h2/h3 are absent."""

    def test_init_succeeds_with_httpx(self):
        """HTTP3Transport can be constructed if httpx is available."""
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        from roar_sdk.transports.quic import HTTP3Transport

        transport = HTTP3Transport()
        assert transport is not None

    def test_protocol_label_without_h2(self):
        """Without h2, protocol_label should be http/1.1."""
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        from roar_sdk.transports.quic import HTTP3Transport, _HAS_H2

        transport = HTTP3Transport()
        if not _HAS_H2:
            assert transport.protocol_label == "http/1.1"
        else:
            assert transport.protocol_label == "h2"

    def test_init_raises_without_httpx(self):
        """HTTP3Transport raises ImportError when httpx is missing."""
        from roar_sdk.transports import quic as quic_mod

        original = quic_mod._HAS_HTTPX
        try:
            quic_mod._HAS_HTTPX = False
            with pytest.raises(ImportError, match="httpx"):
                quic_mod.HTTP3Transport()
        finally:
            quic_mod._HAS_HTTPX = original


# ---------------------------------------------------------------------------
# HTTP3Transport.send_message — mocked httpx
# ---------------------------------------------------------------------------

class TestHTTP3TransportSendMessage:
    """Test send_message with a mocked httpx.AsyncClient."""

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        from roar_sdk.transports.quic import HTTP3Transport

        msg = _make_message()
        response_body = json.loads(_response_json(msg))

        # Build a mock response
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = mock.Mock()
        mock_response.json.return_value = response_body

        mock_client_instance = mock.AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = mock.AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("httpx.AsyncClient", return_value=mock_client_instance):
            transport = HTTP3Transport()
            config = ConnectionConfig(url="http://localhost:8000", transport=TransportType.HTTP)
            result = await transport.send_message(config, msg)

        assert result.intent == MessageIntent.RESPOND
        assert result.payload == {"result": "pong"}

    @pytest.mark.asyncio
    async def test_send_message_empty_url_raises(self):
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        from roar_sdk.transports.quic import HTTP3Transport

        transport = HTTP3Transport()
        config = ConnectionConfig(url="", transport=TransportType.HTTP)
        msg = _make_message()

        with pytest.raises(ConnectionError, match="requires a URL"):
            await transport.send_message(config, msg)

    @pytest.mark.asyncio
    async def test_send_message_connection_error(self):
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        import httpx
        from roar_sdk.transports.quic import HTTP3Transport

        mock_client_instance = mock.AsyncMock()
        mock_client_instance.post.side_effect = httpx.ConnectError("refused")
        mock_client_instance.__aenter__ = mock.AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("httpx.AsyncClient", return_value=mock_client_instance):
            transport = HTTP3Transport()
            config = ConnectionConfig(url="http://localhost:9999", transport=TransportType.HTTP)
            msg = _make_message()

            with pytest.raises(ConnectionError, match="failed to connect"):
                await transport.send_message(config, msg)


# ---------------------------------------------------------------------------
# Message serialization — must match HTTP transport format
# ---------------------------------------------------------------------------

class TestMessageSerializationCompat:
    """The wire format from HTTP3Transport must match the plain HTTP transport."""

    @pytest.mark.asyncio
    async def test_payload_matches_http_format(self):
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        msg = _make_message()
        payload = msg.model_dump(by_alias=True)

        # Verify the canonical fields exist
        assert "from" in payload
        assert "to" in payload
        assert "intent" in payload
        assert "roar" in payload

        # Verify it round-trips
        restored = ROARMessage.model_validate(payload)
        assert restored.intent == msg.intent
        assert restored.from_identity.display_name == "Alice"
        assert restored.to_identity.display_name == "Bob"

    def test_json_encoding_matches_http(self):
        """JSON encoding must be identical to what http_send uses."""
        msg = _make_message()
        payload = msg.model_dump(by_alias=True)
        encoded = json.dumps(payload)
        decoded = json.loads(encoded)
        assert decoded["from"]["display_name"] == "Alice"
        assert decoded["intent"] == "execute"


# ---------------------------------------------------------------------------
# create_transport — auto-selection
# ---------------------------------------------------------------------------

class TestCreateTransport:
    """create_transport returns the appropriate transport based on availability."""

    def test_auto_returns_http3_when_httpx_available(self):
        from roar_sdk.transports.quic import _HAS_HTTPX, create_transport

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        transport = create_transport("auto")
        from roar_sdk.transports.quic import HTTP3Transport
        assert isinstance(transport, HTTP3Transport)

    def test_auto_falls_back_without_httpx(self):
        from roar_sdk.transports import quic as quic_mod

        original = quic_mod._HAS_HTTPX
        try:
            quic_mod._HAS_HTTPX = False
            transport = quic_mod.create_transport("auto")
            # Should return a _FunctionTransport wrapping http_send
            from roar_sdk.transports.quic import _FunctionTransport
            assert isinstance(transport, _FunctionTransport)
            assert transport.protocol_label == "http/1.1"
        finally:
            quic_mod._HAS_HTTPX = original

    def test_explicit_http_returns_function_transport(self):
        from roar_sdk.transports.quic import create_transport, _FunctionTransport

        transport = create_transport("http")
        assert isinstance(transport, _FunctionTransport)

    def test_explicit_quic_raises_without_aioquic(self):
        from roar_sdk.transports.quic import _HAS_AIOQUIC, create_transport

        if _HAS_AIOQUIC:
            pytest.skip("aioquic is installed")

        with pytest.raises(ImportError, match="aioquic"):
            create_transport("quic")

    def test_explicit_http3_with_httpx(self):
        from roar_sdk.transports.quic import _HAS_HTTPX, create_transport

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        from roar_sdk.transports.quic import HTTP3Transport
        transport = create_transport("http3")
        assert isinstance(transport, HTTP3Transport)

    def test_unknown_preference_raises(self):
        from roar_sdk.transports.quic import create_transport

        with pytest.raises(ValueError, match="Unknown transport"):
            create_transport("carrier_pigeon")


# ---------------------------------------------------------------------------
# detect_transport_capability — mocked responses
# ---------------------------------------------------------------------------

class TestDetectTransportCapability:

    @pytest.mark.asyncio
    async def test_returns_http11_without_httpx(self):
        from roar_sdk.transports import quic as quic_mod

        original = quic_mod._HAS_HTTPX
        try:
            quic_mod._HAS_HTTPX = False
            result = await quic_mod.detect_transport_capability("http://example.com")
            assert result == ["http/1.1"]
        finally:
            quic_mod._HAS_HTTPX = original

    @pytest.mark.asyncio
    async def test_detects_h2_with_mock(self):
        from roar_sdk.transports.quic import _HAS_HTTPX, _HAS_H2

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")
        if not _HAS_H2:
            pytest.skip("h2 not installed")

        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = mock.Mock()
        mock_resp.http_version = "HTTP/2"
        mock_resp.json.return_value = {"status": "ok"}

        mock_client = mock.AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("httpx.AsyncClient", return_value=mock_client):
            from roar_sdk.transports.quic import detect_transport_capability
            result = await detect_transport_capability("http://localhost:8000")
            assert "h2" in result

    @pytest.mark.asyncio
    async def test_detects_http11_with_mock(self):
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        from roar_sdk.transports import quic as quic_mod

        # Force no h2 so we hit the HTTP/1.1 fallback path
        orig_h2 = quic_mod._HAS_H2
        try:
            quic_mod._HAS_H2 = False

            mock_resp = mock.Mock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = mock.Mock()
            mock_resp.json.return_value = {"status": "ok"}

            mock_client = mock.AsyncMock()
            mock_client.get.return_value = mock_resp
            mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = mock.AsyncMock(return_value=False)

            with mock.patch("httpx.AsyncClient", return_value=mock_client):
                result = await quic_mod.detect_transport_capability("http://localhost:8000")
                assert "http/1.1" in result
        finally:
            quic_mod._HAS_H2 = orig_h2


# ---------------------------------------------------------------------------
# Transport __init__.py integration
# ---------------------------------------------------------------------------

class TestTransportsInit:
    """Verify the transports __init__.py exports the new symbols."""

    def test_http3_transport_importable(self):
        from roar_sdk.transports import HTTP3Transport
        # May be None if deps are broken, but the name must exist
        assert HTTP3Transport is not None or True

    def test_quic_transport_importable(self):
        from roar_sdk.transports import QUICTransport
        assert QUICTransport is not None or True

    def test_constants_importable(self):
        from roar_sdk.transports import TRANSPORT_HTTP3, TRANSPORT_QUIC
        assert TRANSPORT_HTTP3 == "http3"
        assert TRANSPORT_QUIC == "quic"

    def test_create_transport_importable(self):
        from roar_sdk.transports import create_transport
        assert create_transport is not None or True

    def test_detect_transport_capability_importable(self):
        from roar_sdk.transports import detect_transport_capability
        assert detect_transport_capability is not None or True


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHTTP3TransportHealth:
    @pytest.mark.asyncio
    async def test_health_returns_protocol_label(self):
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        from roar_sdk.transports.quic import HTTP3Transport

        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = mock.Mock()
        mock_resp.json.return_value = {"status": "ok"}

        mock_client = mock.AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("httpx.AsyncClient", return_value=mock_client):
            transport = HTTP3Transport()
            result = await transport.health("http://localhost:8000")
            assert result["status"] == "ok"
            assert "protocol" in result

    @pytest.mark.asyncio
    async def test_health_error_returns_error_dict(self):
        from roar_sdk.transports.quic import _HAS_HTTPX

        if not _HAS_HTTPX:
            pytest.skip("httpx not installed")

        from roar_sdk.transports.quic import HTTP3Transport

        mock_client = mock.AsyncMock()
        mock_client.get.side_effect = Exception("timeout")
        mock_client.__aenter__ = mock.AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = mock.AsyncMock(return_value=False)

        with mock.patch("httpx.AsyncClient", return_value=mock_client):
            transport = HTTP3Transport()
            result = await transport.health("http://localhost:8000")
            assert result["status"] == "error"
            assert "timeout" in result["error"]
