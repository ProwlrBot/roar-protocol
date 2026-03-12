# -*- coding: utf-8 -*-
"""ROAR HTTP Transport — POST /roar/message, GET /roar/events (SSE)."""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict

from ..types import ConnectionConfig, ROARMessage

logger = logging.getLogger(__name__)


async def http_send(config: ConnectionConfig, message: ROARMessage) -> ROARMessage:
    """Send a ROARMessage via HTTP POST and return the response.

    Raises:
        ImportError: If httpx is not installed (pip install roar-sdk[http]).
        ConnectionError: If the request fails.
    """
    try:
        import httpx
    except ImportError:
        raise ImportError(
            "HTTP transport requires httpx. "
            "Install it: pip install 'roar-sdk[http]'"
        )

    url = config.url.rstrip("/")
    if not url:
        raise ConnectionError("HTTP transport requires a URL in ConnectionConfig")

    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-ROAR-Protocol": message.roar,
    }

    if config.auth_method == "jwt" and config.secret:
        headers["Authorization"] = f"Bearer {config.secret}"

    payload = message.model_dump(by_alias=True)

    async with httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_ms / 1000)) as client:
        try:
            response = await client.post(f"{url}/roar/message", json=payload, headers=headers)
            response.raise_for_status()
            return ROARMessage.model_validate(response.json())
        except httpx.ConnectError as exc:
            raise ConnectionError(f"Failed to connect to {url}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise ConnectionError(
                f"HTTP {exc.response.status_code} from {url}: {exc.response.text[:200]}"
            ) from exc


async def http_stream_events(
    config: ConnectionConfig,
    session_id: str = "",
) -> AsyncIterator[Dict[str, Any]]:
    """Subscribe to SSE events from a ROAR agent.

    Yields parsed event data dicts. Compatible with A2A streaming and
    MCP Streamable HTTP transport.
    """
    try:
        import httpx
    except ImportError:
        raise ImportError("HTTP transport requires httpx: pip install 'roar-sdk[http]'")

    url = config.url.rstrip("/")
    params: Dict[str, str] = {}
    if session_id:
        params["session_id"] = session_id

    async with httpx.AsyncClient(timeout=httpx.Timeout(None)) as client:
        async with client.stream(
            "GET",
            f"{url}/roar/events",
            params=params,
            headers={"Accept": "text/event-stream"},
        ) as response:
            response.raise_for_status()
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    event = _parse_sse(event_str)
                    if event:
                        yield event


def _parse_sse(raw: str) -> Dict[str, Any] | None:
    data_lines = []
    for line in raw.strip().split("\n"):
        if line.startswith("data: "):
            data_lines.append(line[6:])
    if not data_lines:
        return None
    try:
        return json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return {"text": "\n".join(data_lines)}
