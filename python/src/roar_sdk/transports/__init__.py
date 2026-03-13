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
        from .websocket import ws_send
        return await ws_send(config, message)

    if config.transport == TransportType.STDIO:
        from .stdio import stdio_send
        return await stdio_send(message)

    raise NotImplementedError(f"Transport not supported: {config.transport}")
