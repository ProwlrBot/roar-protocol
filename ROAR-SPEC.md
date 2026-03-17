# ROAR Protocol Specification v0.3.0

**Real-time Open Agent Runtime**
*Designed by [@kdairatchi](https://github.com/kdairatchi)*

---

## Overview

ROAR is a five-layer protocol for agent identity, discovery, communication, and streaming. It provides a single unified message format for all agent interactions while maintaining backward compatibility with MCP, A2A, and ACP.

ROAR does not replace existing protocols. It unifies them: MCPAdapter and A2AAdapter translate automatically between ROAR messages and their native formats so existing infrastructure keeps working.

---

## Architecture

```
Layer 5: Stream    — Real-time event streaming (SSE, WebSocket)
Layer 4: Exchange  — Message format, signing, verification
Layer 3: Connect   — Transport negotiation (stdio, HTTP, WS, gRPC)
Layer 2: Discovery — Directory service, capability search, federation
Layer 1: Identity  — W3C DID-based agent identity, capability declaration
```

Each layer builds on the one below. An implementation may use only the lower layers (e.g., Identity + Discovery) without requiring the full stack.

---

## Layer 1 — Identity

Agents identify themselves using W3C Decentralized Identifiers (DIDs) with the `did:roar:` method.

### DID Format

```
did:roar:<agent_type>:<slug>-<unique_id>
```

Every agent has an `AgentIdentity` containing a DID, display name, type, capabilities list, version, and optional Ed25519 public key. An `AgentCard` extends identity with a description, skills, channels, endpoints, and formal capability declarations.

**Agent types:** `agent`, `tool`, `human`, `ide`

**JSON Schema:** [`spec/schemas/agent-identity.json`](spec/schemas/agent-identity.json)

See [spec/01-identity.md](spec/01-identity.md) for the full specification.

---

## Layer 2 — Discovery

The `AgentDirectory` provides agent registration, lookup by DID, and capability-based search. Federation across multiple directories is supported by propagating `DiscoveryEntry` records that include the originating hub URL and timestamps.

**JSON Schema:** [`spec/schemas/agent-card.json`](spec/schemas/agent-card.json)

See [spec/02-discovery.md](spec/02-discovery.md) for the full specification.

---

## Layer 3 — Connect

ROAR supports four transport types: `stdio`, `http`, `websocket`, and `grpc`. A `ConnectionConfig` specifies the transport, URL, authentication method (`hmac`, `jwt`, `mtls`, `none`), shared secret, and timeout.

Transport selection uses the endpoints declared in an agent's `AgentCard`. Auto-selection priority: WebSocket > HTTP > stdio.

See [spec/03-connect.md](spec/03-connect.md) for the full specification.

---

## Layer 4 — Exchange

All communication uses a single `ROARMessage` format. Seven intent types cover all interaction patterns.

### ROARMessage Wire Format

```json
{
  "roar": "1.0",
  "id": "msg_a1b2c3d4e5",
  "from": {
    "did": "did:roar:agent:architect-f5e6d7c8",
    "display_name": "architect",
    "agent_type": "agent",
    "capabilities": ["python", "architecture"],
    "version": "1.0"
  },
  "to": {
    "did": "did:roar:agent:frontend-k1l2m3n4",
    "display_name": "frontend",
    "agent_type": "agent",
    "capabilities": ["react", "typescript"],
    "version": "1.0"
  },
  "intent": "delegate",
  "payload": {"task": "implement UserDashboard", "priority": "high"},
  "context": {"session_id": "sess_abc123"},
  "auth": {"signature": "hmac-sha256:a1b2c3...", "timestamp": 1710000000.0},
  "timestamp": 1710000000.0
}
```

### The 7 Intents

| Intent | Direction | Use case |
|:-------|:----------|:---------|
| `execute` | Agent → Tool | Run a tool or command |
| `delegate` | Agent → Agent | Hand off a task |
| `update` | Agent → IDE | Report progress |
| `ask` | Agent → Human | Request input or approval |
| `respond` | Any → Any | Reply to any message |
| `notify` | Any → Any | One-way notification |
| `discover` | Any → Directory | Find agents by capability |

### Signing

HMAC-SHA256 over the canonical body:

```python
canonical = json.dumps(
    {
        "id": msg.id,
        "from": msg.from_identity.did,
        "to": msg.to_identity.did,
        "intent": msg.intent,
        "payload": msg.payload,
        "context": msg.context,
        "timestamp": msg.auth.get("timestamp"),
    },
    sort_keys=True,
)
signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
# Stored as: "hmac-sha256:<hex>"
```

The signing body covers **all security-relevant fields**: id, both DIDs, intent, payload, context, and the auth timestamp (set before signing). Timestamp is included for replay protection — messages older than 5 minutes are rejected.

**JSON Schema:** [`spec/schemas/roar-message.json`](spec/schemas/roar-message.json)

See [spec/04-exchange.md](spec/04-exchange.md) for the full specification.

---

## Layer 5 — Stream

Real-time events use `StreamEvent` objects. Eight event types cover everything from tool calls to virtual world updates.

### StreamEvent Wire Format

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

### The 8 Event Types

| Type | Source | Use case |
|:-----|:-------|:---------|
| `tool_call` | Agent | Track which tools agents are calling |
| `mcp_request` | MCP Client | Monitor incoming MCP requests |
| `reasoning` | Agent | Show agent thinking in real-time |
| `task_update` | War Room | Track mission board changes |
| `monitor_alert` | Monitor | Web/API change notifications |
| `agent_status` | Agent | Agent went idle/busy/offline |
| `checkpoint` | Agent | Checkpoint for crash recovery |
| `world_update` | AgentVerse | Virtual world state changes |

**JSON Schema:** [`spec/schemas/stream-event.json`](spec/schemas/stream-event.json)

See [spec/05-stream.md](spec/05-stream.md) for the full specification.

---

## Backward Compatibility

### MCP Adapter

`MCPAdapter` translates MCP tool calls to ROAR `execute` messages and back:

```python
# MCP → ROAR
roar_msg = MCPAdapter.mcp_to_roar("read_file", {"path": "src/main.py"}, agent)

# ROAR → MCP
mcp_call = MCPAdapter.roar_to_mcp(roar_msg)
# → {"tool": "read_file", "params": {"path": "src/main.py"}}
```

### A2A Adapter

`A2AAdapter` translates A2A agent tasks to ROAR `delegate` messages:

```python
# A2A → ROAR
roar_msg = A2AAdapter.a2a_task_to_roar(task, sender, receiver)

# ROAR → A2A
a2a_task = A2AAdapter.roar_to_a2a(roar_msg)
# Original protocol preserved in context.protocol = "a2a"
```

### ACP Adapter

ACP operation types map to ROAR `MessageIntent` values. ACP is the protocol used by IDE integrations (Claude Code `prowlr acp` command).

---

## SDK Usage

### Client

```python
from prowlrbot.protocols.roar import AgentIdentity, AgentCard, MessageIntent
from prowlrbot.protocols.sdk.client import ROARClient

identity = AgentIdentity(display_name="my-agent", capabilities=["code-review"])
client = ROARClient(identity, signing_secret="shared-secret")

card = AgentCard(identity=identity, description="Reviews code")
client.register(card)

response = await client.send_remote(
    to_agent_id="did:roar:agent:reviewer-abc123",
    intent=MessageIntent.DELEGATE,
    content={"task": "review", "files": ["main.py"]},
)
```

### Server

```python
from prowlrbot.protocols.roar import AgentIdentity, MessageIntent, ROARMessage
from prowlrbot.protocols.sdk.server import ROARServer

identity = AgentIdentity(display_name="code-reviewer")
server = ROARServer(identity, port=8089, signing_secret="shared-secret")

@server.on(MessageIntent.DELEGATE)
async def handle_delegate(msg: ROARMessage) -> ROARMessage:
    return ROARMessage(
        **{"from": server.identity, "to": msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={"status": "ok", "review": "LGTM"},
        context={"in_reply_to": msg.id},
    )
```

---

## HTTP Endpoints

A ROAR-compliant server exposes:

| Endpoint | Method | Description |
|:---------|:-------|:------------|
| `/roar/message` | POST | Receive a ROARMessage, return a response |
| `/roar/agents` | GET | List registered agents (discovery) |
| `/roar/agents/{did}` | GET | Get a specific agent's card |
| `/roar/agents/register` | POST | Register an agent card |
| `/roar/events` | GET | SSE stream of StreamEvents |

---

## Security

- **Message signing**: HMAC-SHA256 over `{id, from DID, to DID, intent, payload, context, timestamp}` with a shared secret.
- **Replay protection:** Implementations MUST reject messages whose `auth.timestamp` differs from the server's wall clock by more than 300 seconds (5 minutes). Implementations MUST additionally record seen message IDs (the `id` field) for a minimum of 600 seconds and reject any message whose ID has been seen before (HTTP 409 Conflict). Timestamp windowing alone is insufficient — a nonce/ID deduplication store is required for full replay protection.
- **Identity verification**: DID resolution confirms agent identity before accepting messages.
- **Transport encryption**: TLS required for HTTP and WebSocket transports in production.
- **Ed25519**: Optional public key in `AgentIdentity.public_key` for asymmetric signing (spec complete, SDK implementation pending).
- **Secret management**: Signing secrets are never transmitted in message payloads.

---

## Versioning

The spec is versioned in [`spec/VERSION.json`](spec/VERSION.json). Spec changes follow semantic versioning:

- **Patch** (`0.2.x`): Clarifications, doc fixes, new examples. No wire format change.
- **Minor** (`0.x.0`): New optional fields, new event types. Backward compatible.
- **Major** (`x.0.0`): Breaking changes to wire format or required fields.

---

## References

- [MCP Specification v2025-11-25](https://spec.modelcontextprotocol.io/) — Anthropic / AAIF. Tool integration protocol.
- [A2A Protocol v0.3.0](https://github.com/google/A2A) — Google / Linux Foundation. Agent-to-agent collaboration.
- [ACP Specification v0.2.3](https://github.com/agntcy/acp-spec) — Agntcy Collective. IDE-agent communication.
- [W3C DID Core v1.0](https://www.w3.org/TR/did-core/) — W3C Recommendation, July 2022. Decentralized identifiers.
- [W3C VC Data Model v2.0](https://www.w3.org/TR/vc-data-model-2.0/) — W3C Recommendation, March 2025.
- [DIDComm Messaging v2.1](https://identity.foundation/didcomm-messaging/spec/) — Decentralized Identity Foundation.
- [AAIF Technical Committee](https://github.com/aaif/technical-committee) — Agentic AI Foundation, Linux Foundation.
- [IETF BANDAID](https://datatracker.ietf.org/doc/draft-mozleywilliams-dnsop-dnsaid/) — DNS-based Agent Discovery.
