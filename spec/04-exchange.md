# Layer 4: Exchange

> Unified message format, 7 intents, HMAC-SHA256 signing, protocol adapters

---

## Overview

The Exchange layer defines the universal message format for all ROAR communication. One message type, one signing scheme, seven intents — covers everything from tool calls to agent delegation to human questions.

---

## ROARMessage

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `roar` | string | Yes | Protocol version (default: "1.0") |
| `id` | string | Auto-generated | Unique message ID (`msg_<random>`) |
| `from` | AgentIdentity | Yes | Sender identity |
| `to` | AgentIdentity | Yes | Receiver identity |
| `intent` | MessageIntent | Yes | What the sender wants |
| `payload` | dict | Yes | Message content |
| `context` | dict | Optional | Session context, metadata |
| `auth` | dict | Optional | Authentication (signature, timestamp) |
| `timestamp` | float | Auto-generated | Unix timestamp |

---

## Wire Format

### EXECUTE (Agent → Tool)

```json
{
  "roar": "1.0",
  "id": "msg_a1b2c3d4e5",
  "from": {"did": "did:roar:agent:architect-f5e6d7c8", "display_name": "architect", "agent_type": "agent"},
  "to": {"did": "did:roar:tool:shell-9a8b7c6d", "display_name": "shell", "agent_type": "tool"},
  "intent": "execute",
  "payload": {"action": "run_command", "params": {"command": "pytest tests/ -v"}},
  "auth": {"signature": "hmac-sha256:a1b2c3...", "timestamp": 1710000000.0},
  "timestamp": 1710000000.0
}
```

### DELEGATE (Agent → Agent)

```json
{
  "roar": "1.0",
  "id": "msg_f6g7h8i9j0",
  "from": {"did": "did:roar:agent:architect-f5e6d7c8", "display_name": "architect"},
  "to": {"did": "did:roar:agent:frontend-k1l2m3n4", "display_name": "frontend"},
  "intent": "delegate",
  "payload": {"action": "implement-component", "params": {"component": "UserDashboard"}},
  "timestamp": 1710000000.0
}
```

---

## Message Intents

| Intent | Direction | Use case |
|--------|-----------|----------|
| `execute` | Agent → Tool | Run a tool/command |
| `delegate` | Agent → Agent | Delegate a task |
| `update` | Agent → IDE | Report progress |
| `ask` | Agent → Human | Request input |
| `respond` | Any → Any | Reply to a message |
| `notify` | Any → Any | One-way notification |
| `discover` | Any → Directory | Find agents |

---

## Signing

### HMAC-SHA256

```python
canonical = json.dumps(
    {"id": msg.id, "intent": msg.intent, "payload": msg.payload},
    sort_keys=True,
)
signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
```

Stored as: `"hmac-sha256:<hex_digest>"`

---


## Security Verification Profile (Normative)

Implementations **MUST** enforce all checks below before dispatching a message to business logic:

1. **Signature scheme allowlist**: accept only configured schemes (default: `hmac-sha256`, `ed25519`). Unknown schemes **MUST** be rejected.
2. **Recipient binding**: `to.did` **MUST** equal the local receiver DID (or an explicitly configured alias) to prevent confused-deputy forwarding.
3. **Timestamp window**: `auth.timestamp` **MUST** be present and numeric. Receivers **MUST** reject messages older than the replay window (default 300s) and **MUST** reject messages too far in the future (default 30s skew allowance).
4. **Replay cache**: receivers **MUST** maintain a deduplication cache keyed by message `id` for at least the replay window. Duplicate IDs within the window **MUST** be rejected.
5. **Canonical body parity**: signing and verification **MUST** use identical canonicalization for all covered fields (`id`, `from.did`, `to.did`, `intent`, `payload`, `context`, `auth.timestamp`).
6. **Fail closed**: malformed `auth` objects, missing required fields, or verification errors **MUST** return an auth failure and **MUST NOT** reach intent handlers.

### Key and Trust Binding (Normative)

- For `ed25519`, verifiers **MUST** obtain the public key from a trusted identity record (DID document or trusted directory). Verifiers **MUST NOT** trust a key supplied only inside the message body.
- For HMAC, deployments **SHOULD** support key identifiers (`kid`) and overlap old/new keys during rotation; verifiers **MUST** reject unknown `kid` values.
- Implementations **SHOULD** include the negotiated protocol/version in policy checks and **MUST** reject unknown major versions to prevent downgrade ambiguity.

## Protocol Adapters

### MCP ↔ ROAR

```python
# MCP → ROAR
roar_msg = MCPAdapter.mcp_to_roar("read_file", {"path": "src/main.py"}, agent)
# ROAR → MCP
mcp_call = MCPAdapter.roar_to_mcp(roar_msg)
# → {"tool": "read_file", "params": {"path": "src/main.py"}}
```

### A2A ↔ ROAR

```python
# A2A → ROAR
roar_msg = A2AAdapter.a2a_task_to_roar(task, sender, receiver)
# ROAR → A2A
a2a_task = A2AAdapter.roar_to_a2a(roar_msg)
```

---

## Design Decisions

1. **Single message type** — one `ROARMessage` for everything, differentiated by `intent`
2. **Canonical JSON signing** — `sort_keys=True` ensures deterministic serialization
3. **Adapter pattern** — backward compatibility via adapters, keeping the core clean
4. **Full identities in from/to** — enables capability-aware routing without directory lookups
