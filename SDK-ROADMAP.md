# ROAR SDK Roadmap

> Status of Python and TypeScript SDK implementations relative to the spec.
> This document is for contributors who want to close implementation gaps.

---

## Current Status

| Layer | Spec | Python SDK | TypeScript SDK |
|:------|:----:|:----------:|:--------------:|
| 1 — Identity | ✅ Complete | ✅ `roar.py` — `AgentIdentity`, `AgentCard`, DID generation | ⚠️ Types exist, field names diverge (see §Types) |
| 2 — Discovery | ✅ Complete | ✅ `roar.py` — `AgentDirectory`, `AgentCard`, in-memory | ⚠️ Not implemented |
| 3 — Connect | ✅ Complete | ✅ `sdk/transports/` — HTTP, WebSocket, stdio | ⚠️ Not implemented |
| 4 — Exchange | ✅ Complete | ✅ `roar.py` — `ROARMessage`, `MessageIntent`, HMAC-SHA256 | ⚠️ Implemented, but enum/field names wrong |
| 5 — Stream | ✅ Complete | ✅ `sdk/streaming/` — `EventBus`, backpressure, dedup | ⚠️ `StreamEventType` enum values wrong |

**Python SDK reference:** `prowlrbot/src/prowlrbot/protocols/`
**TypeScript SDK reference:** `prowlrbot/packages/roar-sdk-ts/`

---

## Critical: Python / TypeScript Type Divergence

Python is the source of truth. TypeScript must be aligned to Python field names and enum values.

### MessageIntent — Must Fix

| Python (canonical) | TypeScript (current) | Action |
|:-------------------|:---------------------|:-------|
| `execute` | `tool_call` | Rename to `execute` |
| `delegate` | — | Add |
| `update` | — | Add |
| `ask` | `query` | Rename to `ask` |
| `respond` | `response` | Rename to `respond` |
| `notify` | — | Add |
| `discover` | `negotiate` | Rename to `discover` |
| — | `heartbeat` | Remove → use `StreamEventType.AGENT_STATUS` |
| — | `error` | Remove → use `RESPOND` with `payload.error` |
| — | `stream_start/data/end` | Remove → use `StreamEvent` system |

### AgentIdentity — Must Fix

| Python (canonical) | TypeScript (current) | Action |
|:-------------------|:---------------------|:-------|
| `did` | `agent_id` | Rename to `did` |
| `display_name` | `display_name` | ✅ Same |
| `agent_type` | `agent_type` | ✅ Same |
| `capabilities: string[]` | `capabilities: AgentCapability[]` | Simplify to `string[]` |
| `version: str` | `version: string` | ✅ Same |
| `public_key: Optional[str]` | `public_key?: string` | ✅ Same |

### ROARMessage — Must Fix

| Python (canonical) | TypeScript (current) | Action |
|:-------------------|:---------------------|:-------|
| `roar: str` | — | Add |
| `id: str` | `id: string` | ✅ Same |
| `from_identity: AgentIdentity` | `from_agent: string` | Change to full identity object |
| `to_identity: AgentIdentity` | `to_agent: string` | Change to full identity object |
| `intent: MessageIntent` | `type: MessageIntent` | Rename to `intent` |
| `payload: dict` | `content: any` | Rename to `payload` |
| `context: dict` | `metadata: any` | Rename to `context` |
| `auth: {signature, timestamp}` | `signature: string` | Change to `auth` object |
| `timestamp: float` | `timestamp: string` (ISO) | Change to Unix float |

### StreamEventType — Must Fix

| Python (canonical) | TypeScript (current) | Action |
|:-------------------|:---------------------|:-------|
| `tool_call` | `started` | Rename |
| `mcp_request` | `data` | Rename |
| `reasoning` | `progress` | Rename |
| `task_update` | `completed` | Rename |
| `monitor_alert` | `error` | Rename |
| `agent_status` | `cancelled` | Rename |
| `checkpoint` | — | Add |
| `world_update` | — | Add |

### Signing Canonical Body — Must Fix

Both SDKs must sign the same body. Python signs:

```python
json.dumps({
    "id": msg.id,
    "from": msg.from_identity.did,
    "to": msg.to_identity.did,
    "intent": msg.intent,
    "payload": msg.payload,
    "context": msg.context,
    "timestamp": msg.auth.get("timestamp"),
}, sort_keys=True)
```

TypeScript currently signs only `{id, intent, payload}` — missing `from`, `to`, `context`, `timestamp`. This means a message signed in Python cannot be verified in TypeScript and vice versa.

The golden fixture at `tests/conformance/golden/signature.json` defines the expected HMAC value for a fixed input. Any compliant SDK must produce the same value.

---

## Open Tasks by Layer

### Layer 1 — Identity

| Task | SDK | Priority |
|:-----|:----|:---------|
| Align field names: `agent_id` → `did`, etc. | TypeScript | **Critical** |
| Ed25519 signing/verification | Python (partial), TypeScript (missing) | High |
| DID document generation (`did:roar:` method) | Python (done), TypeScript (missing) | Medium |
| Delegation tokens (scoped capability grants) | Python (partial), TypeScript (missing) | Medium |

### Layer 2 — Discovery

| Task | SDK | Priority |
|:-----|:----|:---------|
| In-memory `AgentDirectory` | TypeScript (missing) | High |
| SQLite-backed directory | Python (done at `sdk/discovery/sqlite_directory.py`) | — |
| Hub federation (cross-machine sync) | Python (partial), TypeScript (missing) | Medium |
| DNS-based discovery (IETF BANDAID alignment) | Both (missing) | Low |

### Layer 3 — Connect

| Task | SDK | Priority |
|:-----|:----|:---------|
| HTTP transport (send/receive) | Python (done), TypeScript (missing) | High |
| WebSocket transport | Python (done), TypeScript (missing) | High |
| stdio transport | Python (done), TypeScript (missing) | Medium |
| gRPC transport | Both (missing) | Low |
| Transport auto-selection | Python (done), TypeScript (missing) | High |

### Layer 4 — Exchange

| Task | SDK | Priority |
|:-----|:----|:---------|
| Unify MessageIntent enum values | TypeScript | **Critical** |
| Unify ROARMessage field names | TypeScript | **Critical** |
| Unify signing canonical body | TypeScript | **Critical** |
| ACP adapter | Python (stub), TypeScript (missing) | Medium |

### Layer 5 — Stream

| Task | SDK | Priority |
|:-----|:----|:---------|
| Unify StreamEventType enum values | TypeScript | **Critical** |
| EventBus pub/sub | Python (done), TypeScript (missing) | High |
| SSE transport binding | Python (done via A2A server), TypeScript (missing) | High |
| AIMD backpressure | Python (done), TypeScript (missing) | Medium |
| Deduplication filter | Python (done), TypeScript (missing) | Low |

---

## Conformance Testing

Any SDK that claims ROAR compliance must pass all golden fixtures in `tests/conformance/golden/`:

1. **`identity.json`** — parse the golden AgentIdentity, verify DID format, round-trip serialize
2. **`message.json`** — parse the golden ROARMessage, verify all field names and intent value
3. **`stream-event.json`** — parse the golden StreamEvent, verify type enum value
4. **`signature.json`** — reproduce the HMAC-SHA256 signature for the given input and secret

Run Python conformance: `pytest tests/conformance/`
Run TypeScript conformance: `npm test -- conformance` (pending implementation)

---

## How to Contribute

1. Pick a task from the tables above
2. Open an issue using the [Spec Change template](.github/ISSUE_TEMPLATE/spec_change.md) if you're proposing a spec change
3. For SDK work, open PRs in [prowlrbot](https://github.com/ProwlrBot/prowlrbot) and reference this doc
4. Add or update golden fixtures if you change the canonical types
5. Bump `spec/VERSION.json` when spec (not SDK) changes are merged

---

## Non-Goals

These are explicitly out of scope for the ROAR core spec:

- **Billing / credits** — handled at the platform layer (ProwlrBot marketplace)
- **Access control lists** — layer on top of identity via `require_approval_for` in AutonomyPolicy
- **Persistent message queuing** — transport-level concern, not protocol-level
- **Content encryption** — use TLS at the transport layer; ROAR signs but does not encrypt payloads
