# Layer 5: Stream

> Real-time event streaming, 8 event types, pub/sub, SSE transport

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

---

## Overview

The Stream layer provides real-time event streaming for monitoring, coordination, and UI updates. Events flow from agents to dashboards, other agents, or external systems.

---

## Stream Event Types

| Event Type | Source | Use case |
|------------|--------|----------|
| `tool_call` | Agent | Track which tools agents are calling |
| `mcp_request` | MCP Client | Monitor incoming MCP requests |
| `reasoning` | Agent | Show agent thinking in real-time |
| `task_update` | War Room | Track mission board changes |
| `monitor_alert` | Monitor | Web/API change notifications |
| `agent_status` | Agent | Agent went idle/busy/offline |
| `checkpoint` | Agent | Checkpoint for crash recovery |
| `world_update` | AgentVerse | Virtual world state changes |

---

## Wire Format

### StreamEvent

```json
{
  "type": "task_update",
  "source": "did:roar:agent:architect-a1b2c3d4",
  "session_id": "sess_abc123",
  "data": {
    "task_id": "task_xyz",
    "status": "completed",
    "summary": "Implemented REST API endpoints"
  },
  "timestamp": 1710000000.0
}
```

---

## EventBus

The in-process event distribution system:

```python
from prowlrbot.protocols.sdk import EventBus
from prowlrbot.protocols.roar import StreamEvent, StreamEventType

bus = EventBus()

# Subscribe to task updates
async def on_task_update(event: StreamEvent):
    print(f"Task {event.data['task_id']} → {event.data['status']}")

bus.subscribe("task_update", on_task_update)

# Publish
event = StreamEvent(
    type=StreamEventType.TASK_UPDATE,
    source="did:roar:agent:architect-a1b2c3d4",
    data={"task_id": "task_xyz", "status": "completed"},
)
await bus.publish(event)
```

---

## SSE Transport

Events stream to web dashboards via Server-Sent Events:

```
GET /a2a/events/stream
Accept: text/event-stream

data: {"type": "task_update", "source": "did:roar:agent:architect-...", "data": {...}}
data: {"type": "tool_call", "source": "did:roar:agent:frontend-...", "data": {...}}
```

The A2A server (`src/prowlrbot/protocols/a2a_server.py`) provides this SSE endpoint backed by the ROAR EventBus.

---

## Integration with ProwlrHub

| War Room Action | Stream Event |
|----------------|--------------|
| Agent registers | `agent_status` (idle) |
| Task claimed | `task_update` (claimed) |
| Task completed | `task_update` (completed) |
| File locked | `task_update` (lock info) |
| Broadcast sent | `agent_status` (message) |
| Finding shared | `task_update` (finding) |

---

## Design Decisions

1. **8 fixed event types** — Implementations MUST use only the defined event types; custom values are NOT permitted on the wire.
2. **SSE over WebSocket** — SSE SHOULD be used for server-to-client streaming; WebSocket MAY be used where bidirectionality is needed.
3. **In-process EventBus** — No external message broker is REQUIRED for compliant implementations.
4. **Source is a DID** — The `source` field MUST be a valid DID; events MUST always be attributable for audit trails.
