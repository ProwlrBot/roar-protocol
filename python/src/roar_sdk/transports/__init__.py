# -*- coding: utf-8 -*-
"""ROAR transport dispatcher. Routes messages based on ConnectionConfig.transport."""

from __future__ import annotations

from ..types import ConnectionConfig, ROARMessage, TransportType


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
        raise NotImplementedError(
            "WebSocket transport is not yet implemented in the standalone SDK. "
            "Use HTTP transport or install ProwlrBot for the full SDK."
        )

    if config.transport == TransportType.STDIO:
        raise NotImplementedError(
            "stdio transport is not yet implemented in the standalone SDK."
        )

    raise NotImplementedError(f"Transport not supported: {config.transport}")
