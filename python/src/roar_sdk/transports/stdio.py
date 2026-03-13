# -*- coding: utf-8 -*-
"""ROAR stdio Transport — newline-delimited JSON over stdin/stdout.

Suitable for local subprocess agent communication (e.g. MCP stdio mode).
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from ..types import ROARMessage


async def stdio_send(message: ROARMessage) -> ROARMessage:
    """Send a ROARMessage via stdio (newline-delimited JSON).

    Writes one JSON line to stdout, reads one JSON line from stdin.
    Non-blocking: uses asyncio.get_event_loop().run_in_executor so the
    event loop is not blocked during the synchronous read.

    This is the ROAR equivalent of the MCP stdio transport — it lets two
    processes communicate by piping each other's stdin/stdout.

    Args:
        message: The message to send (should already be signed).

    Returns:
        The response ROARMessage read from stdin.
    """
    loop = asyncio.get_event_loop()
    payload = message.model_dump(by_alias=True)
    line = json.dumps(payload, separators=(",", ":"))

    # Write to stdout (non-blocking via executor)
    await loop.run_in_executor(None, _write_line, line)

    # Read response from stdin (non-blocking via executor)
    raw = await loop.run_in_executor(None, _read_line)
    if not raw:
        raise ConnectionError("stdio_send: EOF on stdin — remote agent closed")

    return ROARMessage.model_validate(json.loads(raw))


def _write_line(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _read_line() -> str:
    return sys.stdin.readline().rstrip("\n")
