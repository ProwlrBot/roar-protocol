# Layer 3: Connect

> Transport negotiation, session management, keep-alive, connection lifecycle

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

---

## Overview

The Connect layer handles how agents establish and maintain connections. ROAR supports multiple transport protocols and auto-selects the best one based on context.

The Connect layer provides:
- **Transport negotiation** — auto-select stdio, HTTP, WebSocket, or gRPC
- **Session management** — persistent sessions with keep-alive
- **Connection lifecycle** — connect, heartbeat, disconnect, reconnect
- **Authentication** — HMAC, JWT, mTLS, or open

---

## Transport Types

| Transport | When to use | Latency | Bidirectional |
|-----------|------------|---------|---------------|
| `stdio` | Claude Code terminals, MCP servers | Lowest | Yes (via stdio) |
| `http` | REST APIs, HTTP bridge, cross-machine | Low | No (request/response) |
| `websocket` | Real-time dashboards, streaming | Low | Yes |
| `grpc` | High-throughput, binary serialization | Lowest | Yes |

### Auto-Selection Rules

```
MCP context (Claude Code)     → stdio
PROWLR_HUB_URL is set         → http (via bridge)
Dashboard/console connected    → websocket
High-throughput batch          → grpc
```

---

## Wire Format

### ConnectionConfig

```json
{
  "transport": "http",
  "url": "http://192.168.1.100:8099",
  "auth_method": "hmac",
  "secret": "shared-secret-key",
  "timeout_ms": 30000
}
```

---

## Connection Lifecycle

### 1. Connect

```
Agent                          Hub/Server
  │                                │
  ├── Register (name, caps) ──────→│
  │                                ├── Create agent entry
  │                                ├── Assign agent_id
  │←── agent_id, room_id ─────────┤
  │                                │
```

### 2. Heartbeat

Agents MUST send heartbeats every 60 seconds. If no heartbeat is received for 5 minutes, the agent MUST be considered dead and its locks released.

### 3. Dead Agent Sweep

The hub periodically sweeps for dead agents:
- Finds agents with `last_heartbeat` > 5 minutes ago
- Releases all their file locks
- Returns their tasks to "pending"
- Marks agents as "disconnected"

### 4. Graceful Disconnect

On disconnect, all resources are cleaned up immediately without waiting for the sweep.

---

## Authentication Methods

| Method | How it works | Best for |
|--------|-------------|----------|
| `hmac` | HMAC-SHA256 signature on message body | Default, shared-secret environments |
| `jwt` | JWT bearer token in auth header | Web APIs, multi-tenant |
| `mtls` | Mutual TLS certificates | Production, zero-trust |
| `none` | No authentication | Local development, same-machine |

---

## ProwlrHub Connection Modes

### Local Mode (stdio → SQLite)

```
Claude Code Terminal → MCP stdio → ProwlrHub MCP Server → SQLite WAL
```

No network, no bridge. All terminals on the same machine share one SQLite file.

### Remote Mode (stdio → HTTP → SQLite)

```
Claude Code Terminal → MCP stdio → ProwlrHub MCP Server
    → Detects PROWLR_HUB_URL → HTTP Bridge Client (urllib)
    → HTTP Bridge Server (FastAPI :8099) → SQLite WAL
```

The MCP server auto-detects `PROWLR_HUB_URL` and routes all operations through the HTTP bridge.
