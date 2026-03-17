# -*- coding: utf-8 -*-
"""ROAR transport dispatcher. Routes messages based on ConnectionConfig.transport."""

from __future__ import annotations

from ..types import ConnectionConfig, ROARMessage, TransportType

# Import QUIC/HTTP3 transports with graceful fallback
try:
    from .quic import (
        HTTP3Transport,
        QUICTransport,
        TRANSPORT_HTTP3,
        TRANSPORT_QUIC,
        create_transport,
        detect_transport_capability,
    )
except Exception:  # pragma: no cover — import may fail if dependencies are broken
    HTTP3Transport = None  # type: ignore[assignment,misc]
    QUICTransport = None  # type: ignore[assignment,misc]
    TRANSPORT_HTTP3 = "http3"
    TRANSPORT_QUIC = "quic"
    create_transport = None  # type: ignore[assignment]
    detect_transport_capability = None  # type: ignore[assignment]

__all__ = [
    "send_message",
    "HTTP3Transport",
    "QUICTransport",
    "TRANSPORT_HTTP3",
    "TRANSPORT_QUIC",
    "create_transport",
    "detect_transport_capability",
]


async def send_message(
    config: ConnectionConfig,
    message: ROARMessage,
    signing_secret: str = "",
) -> ROARMessage:
    """Send a ROAR message using the transport specified in config.

    Args:
        config: Connection configuration (transport, URL, auth).
        message: The message to send (should already be signed).
        signing_secret: Used only if the transport needs to add auth headers.

    Returns:
        The response ROARMessage from the remote agent.

    Raises:
        ConnectionError: If the transport fails.
        ImportError: If the required transport library is not installed.
        NotImplementedError: If the transport type is not yet implemented.
    """
    if config.transport == TransportType.HTTP:
        from .http import http_send
        return await http_send(config, message)

    if config.transport == TransportType.WEBSOCKET:
        from .websocket import ws_send
        return await ws_send(config, message)

    if config.transport == TransportType.STDIO:
        from .stdio import stdio_send
        return await stdio_send(message)

    # Support QUIC/HTTP3 via string comparison (TransportType enum doesn't
    # include these yet, but ConnectionConfig.transport may be overridden).
    transport_str = str(config.transport)
    if transport_str in (TRANSPORT_QUIC, TRANSPORT_HTTP3):
        if transport_str == TRANSPORT_QUIC:
            t = QUICTransport()
        else:
            t = HTTP3Transport()  # type: ignore[misc]
        return await t.send_message(config, message, signing_secret)

    raise NotImplementedError(f"Transport not supported: {config.transport}")
