# -*- coding: utf-8 -*-
"""ROAR Protocol — Cross-Protocol Event Streaming Bridge.

Bridges real-time ROAR StreamEvents across protocols. When a ROAR
StreamEvent fires, it can be translated and forwarded to MCP/A2A/ACP
listeners in their native event format.

Bidirectional: incoming MCP notifications or A2A status updates can
be normalised back to ROAR StreamEvents.

Usage::

    from roar_sdk.streaming import EventBus, StreamFilter
    from roar_sdk.event_bridge import EventBridge

    bus = EventBus()
    bridge = EventBridge(bus)

    # Subscribe for MCP-formatted events
    mcp_sub = bridge.subscribe_mcp(StreamFilter(event_types=["task_update"]))

    async for mcp_notification in mcp_sub:
        print(mcp_notification)  # {"jsonrpc": "2.0", "method": "notifications/progress", ...}
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator, Dict, Optional

from .streaming import EventBus, StreamFilter, Subscription
from .types import StreamEvent, StreamEventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------

_ROAR_TO_MCP_METHOD = {
    StreamEventType.TASK_UPDATE: "notifications/progress",
    StreamEventType.TOOL_CALL: "notifications/tools/list_changed",
    StreamEventType.STREAM_START: "notifications/initialized",
    StreamEventType.STREAM_END: "notifications/cancelled",
    StreamEventType.MCP_REQUEST: "notifications/message",
    StreamEventType.REASONING: "notifications/progress",
    StreamEventType.MONITOR_ALERT: "notifications/progress",
    StreamEventType.AGENT_STATUS: "notifications/progress",
    StreamEventType.CHECKPOINT: "notifications/progress",
    StreamEventType.WORLD_UPDATE: "notifications/progress",
    StreamEventType.AGENT_DELEGATE: "notifications/progress",
}

_ROAR_TO_A2A_STATE = {
    StreamEventType.TASK_UPDATE: "working",
    StreamEventType.TOOL_CALL: "working",
    StreamEventType.STREAM_START: "submitted",
    StreamEventType.STREAM_END: "completed",
    StreamEventType.AGENT_DELEGATE: "working",
    StreamEventType.REASONING: "working",
    StreamEventType.MCP_REQUEST: "working",
    StreamEventType.MONITOR_ALERT: "working",
    StreamEventType.AGENT_STATUS: "working",
    StreamEventType.CHECKPOINT: "working",
    StreamEventType.WORLD_UPDATE: "working",
}

_MCP_METHOD_TO_ROAR = {
    "notifications/progress": StreamEventType.TASK_UPDATE,
    "notifications/tools/list_changed": StreamEventType.TOOL_CALL,
    "notifications/initialized": StreamEventType.STREAM_START,
    "notifications/cancelled": StreamEventType.STREAM_END,
    "notifications/message": StreamEventType.MCP_REQUEST,
}

_A2A_STATE_TO_ROAR = {
    "working": StreamEventType.TASK_UPDATE,
    "submitted": StreamEventType.STREAM_START,
    "completed": StreamEventType.STREAM_END,
    "failed": StreamEventType.STREAM_END,
    "canceled": StreamEventType.STREAM_END,
}


def roar_event_to_mcp_notification(event: StreamEvent) -> Dict[str, Any]:
    """Translate a ROAR StreamEvent to an MCP JSON-RPC 2.0 notification.

    MCP notifications have no ``id`` field (fire-and-forget).

    Args:
        event: The ROAR StreamEvent to translate.

    Returns:
        An MCP-formatted notification dict.
    """
    method = _ROAR_TO_MCP_METHOD.get(
        StreamEventType(event.type), "notifications/progress"
    )

    params: Dict[str, Any] = {
        "source": event.source,
        "timestamp": event.timestamp,
    }

    if event.type == StreamEventType.TASK_UPDATE:
        params["progressToken"] = event.session_id or event.data.get("task_id", "")
        params["progress"] = event.data.get("progress", 0)
        params["total"] = event.data.get("total", 100)
        if "message" in event.data:
            params["message"] = event.data["message"]
    elif event.type == StreamEventType.TOOL_CALL:
        params["tool"] = event.data.get("tool", "")
        params["arguments"] = event.data.get("arguments", {})
    elif event.type == StreamEventType.STREAM_START:
        params["protocolVersion"] = event.data.get("protocol_version", "2024-11-05")
        params["capabilities"] = event.data.get("capabilities", {})
    elif event.type == StreamEventType.STREAM_END:
        params["reason"] = event.data.get("reason", "completed")
    else:
        params["data"] = event.data

    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    }


def roar_event_to_a2a_status(
    event: StreamEvent,
    task_id: str = "",
) -> Dict[str, Any]:
    """Translate a ROAR StreamEvent to an A2A task status update.

    Args:
        event: The ROAR StreamEvent to translate.
        task_id: The A2A task ID. Falls back to event session_id or data.

    Returns:
        An A2A task status dict.
    """
    tid = task_id or event.session_id or event.data.get("task_id", "")
    state = _ROAR_TO_A2A_STATE.get(StreamEventType(event.type), "working")

    status: Dict[str, Any] = {"state": state}

    if event.type == StreamEventType.TASK_UPDATE:
        message_text = event.data.get("message", event.data.get("content", ""))
        if message_text:
            status["message"] = {
                "role": "agent",
                "parts": [{"type": "text", "text": str(message_text)}],
            }

    elif event.type == StreamEventType.STREAM_END:
        reason = event.data.get("reason", "")
        if reason:
            status["message"] = {
                "role": "agent",
                "parts": [{"type": "text", "text": reason}],
            }

    elif event.type == StreamEventType.AGENT_DELEGATE:
        delegate_info = event.data.get("delegate_to", "")
        delegation_msg = f"Delegating to {delegate_info}" if delegate_info else "Delegating task"
        status["message"] = {
            "role": "agent",
            "parts": [{"type": "text", "text": delegation_msg}],
        }

    result: Dict[str, Any] = {"id": tid, "status": status}

    if state == "completed" and "result" in event.data:
        result["artifacts"] = [
            {
                "parts": [
                    {"type": "text", "text": str(event.data["result"])}
                ],
            }
        ]

    return result


def mcp_notification_to_roar_event(notification: Dict[str, Any]) -> StreamEvent:
    """Translate an MCP notification to a ROAR StreamEvent.

    Args:
        notification: An MCP JSON-RPC 2.0 notification dict.

    Returns:
        A ROAR StreamEvent.
    """
    method = notification.get("method", "")
    params = notification.get("params") or {}

    event_type = _MCP_METHOD_TO_ROAR.get(method, StreamEventType.TASK_UPDATE)

    source = params.get("source", "")
    session_id = params.get("progressToken", "")
    timestamp = params.get("timestamp", time.time())

    data: Dict[str, Any] = {}

    if method == "notifications/progress":
        data["progress"] = params.get("progress", 0)
        data["total"] = params.get("total", 100)
        if "message" in params:
            data["message"] = params["message"]
    elif method == "notifications/tools/list_changed":
        data["tool"] = params.get("tool", "")
        data["arguments"] = params.get("arguments", {})
    elif method == "notifications/initialized":
        data["protocol_version"] = params.get("protocolVersion", "")
        data["capabilities"] = params.get("capabilities", {})
    elif method == "notifications/cancelled":
        data["reason"] = params.get("reason", "cancelled")
    else:
        data = {k: v for k, v in params.items() if k not in ("source", "timestamp")}

    return StreamEvent(
        type=event_type,
        source=source,
        session_id=str(session_id),
        data=data,
        timestamp=timestamp,
    )


def a2a_status_to_roar_event(
    status: Dict[str, Any],
    task_id: str = "",
) -> StreamEvent:
    """Translate an A2A task status update to a ROAR StreamEvent.

    Args:
        status: An A2A task status dict (may include top-level ``id``).
        task_id: Override task ID.

    Returns:
        A ROAR StreamEvent.
    """
    tid = task_id or status.get("id", "")
    status_block = status.get("status", status)
    state = status_block.get("state", "working")

    event_type = _A2A_STATE_TO_ROAR.get(state, StreamEventType.TASK_UPDATE)

    data: Dict[str, Any] = {"task_id": tid, "state": state}

    message_block = status_block.get("message", {})
    if isinstance(message_block, dict):
        parts = message_block.get("parts", [])
        texts = [p.get("text", "") for p in parts if p.get("type") == "text"]
        if texts:
            data["message"] = "\n".join(texts)

    artifacts = status.get("artifacts", [])
    if artifacts:
        all_text: list[str] = []
        for artifact in artifacts:
            for part in artifact.get("parts", []):
                if part.get("type") == "text":
                    all_text.append(part.get("text", ""))
        if all_text:
            data["result"] = "\n".join(all_text)

    return StreamEvent(
        type=event_type,
        source="",
        session_id=tid,
        data=data,
    )


# ---------------------------------------------------------------------------
# Protocol-specific subscription wrappers
# ---------------------------------------------------------------------------


class MCPEventSubscription:
    """Wraps a ROAR Subscription and yields MCP-formatted notifications.

    Async iterable: each iteration yields an MCP JSON-RPC 2.0 notification
    dict translated from the underlying ROAR StreamEvent.
    """

    def __init__(self, subscription: Subscription) -> None:
        self._subscription = subscription

    @property
    def id(self) -> str:
        return self._subscription.id

    @property
    def closed(self) -> bool:
        return self._subscription.closed

    async def __aiter__(self) -> AsyncIterator[Dict[str, Any]]:
        async for event in self._subscription:
            yield roar_event_to_mcp_notification(event)

    async def get(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Get the next MCP notification, or None on timeout."""
        event = await self._subscription.get(timeout=timeout)
        if event is None:
            return None
        return roar_event_to_mcp_notification(event)

    def close(self) -> None:
        self._subscription.close()


class A2AEventSubscription:
    """Wraps a ROAR Subscription and yields A2A task status dicts.

    Async iterable: each iteration yields an A2A task status dict
    translated from the underlying ROAR StreamEvent.
    """

    def __init__(self, subscription: Subscription, task_id: str = "") -> None:
        self._subscription = subscription
        self._task_id = task_id

    @property
    def id(self) -> str:
        return self._subscription.id

    @property
    def closed(self) -> bool:
        return self._subscription.closed

    async def __aiter__(self) -> AsyncIterator[Dict[str, Any]]:
        async for event in self._subscription:
            yield roar_event_to_a2a_status(event, task_id=self._task_id)

    async def get(self, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
        """Get the next A2A status update, or None on timeout."""
        event = await self._subscription.get(timeout=timeout)
        if event is None:
            return None
        return roar_event_to_a2a_status(event, task_id=self._task_id)

    def close(self) -> None:
        self._subscription.close()


# ---------------------------------------------------------------------------
# EventBridge
# ---------------------------------------------------------------------------


class EventBridge:
    """Cross-protocol event streaming bridge.

    Sits on top of an EventBus and provides protocol-specific subscription
    endpoints. Each subscription transparently translates ROAR StreamEvents
    to the target protocol's native event format.

    Also supports bidirectional translation: incoming MCP/A2A events can be
    normalised to ROAR StreamEvents and published on the bus.

    Usage::

        bus = EventBus()
        bridge = EventBridge(bus)

        mcp_sub = bridge.subscribe_mcp(StreamFilter(event_types=["task_update"]))
        async for notification in mcp_sub:
            send_to_mcp_client(notification)
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._bus = event_bus

    @property
    def event_bus(self) -> EventBus:
        """Access the underlying event bus."""
        return self._bus

    def subscribe_mcp(
        self,
        filter_spec: Optional[StreamFilter] = None,
        buffer_size: Optional[int] = None,
    ) -> MCPEventSubscription:
        """Subscribe and receive events as MCP JSON-RPC 2.0 notifications.

        Translates ROAR StreamEvents to MCP notifications:
          - task_update   -> notifications/progress
          - tool_call     -> notifications/tools/list_changed
          - stream_start  -> notifications/initialized
          - stream_end    -> notifications/cancelled

        Args:
            filter_spec: Optional StreamFilter to restrict events.
            buffer_size: Per-subscriber buffer size.

        Returns:
            An MCPEventSubscription (async iterable of MCP notification dicts).
        """
        sub = self._bus.subscribe(filter_spec=filter_spec, buffer_size=buffer_size)
        return MCPEventSubscription(sub)

    def subscribe_a2a(
        self,
        filter_spec: Optional[StreamFilter] = None,
        buffer_size: Optional[int] = None,
        task_id: str = "",
    ) -> A2AEventSubscription:
        """Subscribe and receive events as A2A task status updates.

        Translates ROAR StreamEvents to A2A task status:
          - task_update    -> {status: {state: "working", message: ...}}
          - stream_end     -> {status: {state: "completed"}}
          - agent_delegate -> status update with delegation info

        Args:
            filter_spec: Optional StreamFilter to restrict events.
            buffer_size: Per-subscriber buffer size.
            task_id: A2A task ID to attach to every status update.

        Returns:
            An A2AEventSubscription (async iterable of A2A status dicts).
        """
        sub = self._bus.subscribe(filter_spec=filter_spec, buffer_size=buffer_size)
        return A2AEventSubscription(sub, task_id=task_id)

    def subscribe_native(
        self,
        filter_spec: Optional[StreamFilter] = None,
        buffer_size: Optional[int] = None,
    ) -> Subscription:
        """Subscribe and receive raw ROAR StreamEvents (pass-through).

        This is equivalent to calling ``event_bus.subscribe()`` directly.

        Args:
            filter_spec: Optional StreamFilter to restrict events.
            buffer_size: Per-subscriber buffer size.

        Returns:
            A standard Subscription (async iterable of StreamEvent).
        """
        return self._bus.subscribe(filter_spec=filter_spec, buffer_size=buffer_size)

    def translate_event(
        self,
        event: StreamEvent,
        target_protocol: str,
    ) -> Dict[str, Any]:
        """Translate a single ROAR StreamEvent to a protocol-specific format.

        Args:
            event: The ROAR StreamEvent.
            target_protocol: Target protocol string ("mcp", "a2a", or "roar").

        Returns:
            A dict in the target protocol's event format.
            Unknown protocols return the ROAR native format.
        """
        protocol = target_protocol.lower()
        if protocol == "mcp":
            return roar_event_to_mcp_notification(event)
        elif protocol == "a2a":
            return roar_event_to_a2a_status(event)
        else:
            # Native ROAR or unknown protocol: return the event as a dict
            return event.model_dump()

    async def ingest_mcp_notification(
        self,
        notification: Dict[str, Any],
    ) -> StreamEvent:
        """Ingest an incoming MCP notification, normalise and publish.

        Args:
            notification: An MCP JSON-RPC 2.0 notification dict.

        Returns:
            The ROAR StreamEvent that was published.
        """
        event = mcp_notification_to_roar_event(notification)
        await self._bus.publish(event)
        return event

    async def ingest_a2a_status(
        self,
        status: Dict[str, Any],
        task_id: str = "",
    ) -> StreamEvent:
        """Ingest an incoming A2A task status update, normalise and publish.

        Args:
            status: An A2A task status dict.
            task_id: Override task ID.

        Returns:
            The ROAR StreamEvent that was published.
        """
        event = a2a_status_to_roar_event(status, task_id=task_id)
        await self._bus.publish(event)
        return event
