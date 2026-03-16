# -*- coding: utf-8 -*-
"""ROAR WebSocket Transport — ws://{url}/roar/ws and /roar/ws/stream."""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from ..types import ConnectionConfig, ROARMessage, StreamEvent

logger = logging.getLogger(__name__)


def _ws_url(config: ConnectionConfig, path: str) -> str:
    """Convert http(s) URL to ws(s) and append path."""
    base = config.url.rstrip("/")
    base = base.replace("https://", "wss://").replace("http://", "ws://")
    if not base.startswith(("ws://", "wss://")):
        base = f"ws://{base}"
    return f"{base}{path}"


async def ws_send(config: ConnectionConfig, message: ROARMessage) -> ROARMessage:
    """Send a ROARMessage via WebSocket and return the response.

    Connects to ws://{config.url}/roar/ws, sends JSON, awaits response JSON.

    Args:
        config: Connection config with transport=WEBSOCKET and url set.
        message: The message to send (should already be signed).

    Raises:
        ImportError: If websockets is not installed (pip install roar-sdk[websocket]).
        ConnectionError: If the WebSocket connection fails.
    """
    try:
        import websockets
    except ImportError:
        raise ImportError(
            "WebSocket transport requires websockets. "
            "Install it: pip install 'roar-sdk[websocket]'"
        )

    url = _ws_url(config, "/roar/ws")
    payload = message.model_dump(by_alias=True)

    try:
        async with websockets.connect(
            url,
            open_timeout=config.timeout_ms / 1000,
            close_timeout=10,
        ) as ws:
            await ws.send(json.dumps(payload))
            raw = await asyncio.wait_for(ws.recv(), timeout=config.timeout_ms / 1000)
            return ROARMessage.model_validate(json.loads(raw))
    except Exception as exc:
        raise ConnectionError(f"WebSocket send to {url} failed: {exc}") from exc


async def ws_subscribe(
    config: ConnectionConfig,
    session_id: str = "",
) -> AsyncIterator[StreamEvent]:
    """Subscribe to streaming events via WebSocket.

    Connects to ws://{config.url}/roar/ws/stream and yields StreamEvent
    objects until the connection is closed.

    Args:
        config: Connection config with transport=WEBSOCKET and url set.
        session_id: Optional session filter sent as a query parameter.

    Raises:
        ImportError: If websockets is not installed.
    """
    try:
        import websockets
    except ImportError:
        raise ImportError(
            "WebSocket transport requires websockets. "
            "Install it: pip install 'roar-sdk[websocket]'"
        )

    path = "/roar/ws/stream"
    if session_id:
        path = f"{path}?session_id={session_id}"
    url = _ws_url(config, path)

    try:
        async with websockets.connect(url) as ws:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                    yield StreamEvent.model_validate(data)
                except Exception as exc:
                    logger.warning("ws_subscribe: failed to parse event: %s", exc)
    except Exception as exc:
        logger.info("ws_subscribe: connection closed: %s", exc)


# asyncio is needed by ws_send — import at module level to avoid repeated lookups
import asyncio  # noqa: E402
