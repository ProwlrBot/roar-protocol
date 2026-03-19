# Layer 4: Exchange

> Unified message format, 7 intents, HMAC-SHA256 signing, protocol adapters

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

---

## Overview

The Exchange layer defines the universal message format for all ROAR communication. One message type, one signing scheme, seven intents — covers everything from tool calls to agent delegation to human questions.

---

## ROARMessage

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `roar` | string | REQUIRED | Protocol version (default: "1.0") |
| `id` | string | Auto-generated | Unique message ID (`msg_<random>`); MUST be unique per message |
| `from` | AgentIdentity | REQUIRED | Sender identity |
| `to` | AgentIdentity | REQUIRED | Receiver identity |
| `intent` | MessageIntent | REQUIRED | What the sender wants; MUST be one of the seven defined intents |
| `payload` | dict | REQUIRED | Message content |
| `context` | dict | OPTIONAL | Session context, metadata |
| `auth` | dict | OPTIONAL | Authentication (signature, timestamp); MUST be present on signed messages |
| `timestamp` | float | Auto-generated | Unix timestamp; MUST be set to the current wall-clock time |

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

Implementations MUST construct the signing body as a canonical JSON object
containing exactly the following seven fields, in alphabetical key order:

| Field | Value |
|-------|-------|
| `context` | `msg.context` |
| `from` | `msg.from_identity.did` (the DID string, not the full identity object) |
| `id` | `msg.id` |
| `intent` | `msg.intent` |
| `payload` | `msg.payload` |
| `timestamp` | `msg.auth["timestamp"]` (the auth timestamp set immediately before signing) |
| `to` | `msg.to_identity.did` (the DID string, not the full identity object) |

Serialization rules:

- Keys MUST be sorted alphabetically at all nesting levels (recursively).
- The reference serialization is Python's `json.dumps(..., sort_keys=True, separators=(", ", ": "))`.
- Array elements within arrays are NOT reordered — `sort_keys` applies only to object keys.
- For delegation tokens specifically, the `capabilities` array MUST be sorted
  lexicographically before signing (see spec/schemas/delegation-token.json).

```python
canonical = json.dumps(
    {
        "context": msg.context,
        "from": msg.from_identity.did,
        "id": msg.id,
        "intent": msg.intent,
        "payload": msg.payload,
        "timestamp": msg.auth.get("timestamp"),
        "to": msg.to_identity.did,
    },
    sort_keys=True,
    separators=(", ", ": "),
)
signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
```

Stored as: `"hmac-sha256:<hex_digest>"`

The signing body covers all security-relevant fields: both DID strings, the message ID, intent, payload, shared context, and the auth timestamp. Implementations **MUST** set `auth.timestamp` to the current wall-clock time immediately before computing the signing body.

Canonical serialization is security critical. Implementations **MUST** use a deterministic encoder that preserves:

- Recursive lexical key ordering.
- Canonical numeric rendering that is interoperable across SDKs.
- Exact field coverage above (no omissions and no additional fields).

Implementations **SHOULD** validate canonicalization against shared golden fixtures in `tests/conformance/golden/signature.json`.

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

## Delegation Tokens (Normative)

Delegation tokens allow an agent to act on behalf of another agent. A delegator issues a signed token granting specific capabilities to a delegate.

### Token Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token_id` | string | REQUIRED | Unique token ID (`tok_<10-hex-chars>`) |
| `delegator_did` | string | REQUIRED | DID of the agent granting the delegation |
| `delegate_did` | string | REQUIRED | DID of the agent receiving the delegation |
| `capabilities` | string[] | REQUIRED | Capabilities granted; MUST be sorted lexicographically before signing |
| `issued_at` | float | REQUIRED | Unix timestamp of issuance |
| `expires_at` | float\|null | OPTIONAL | Unix timestamp of expiry; null means no expiry |
| `max_uses` | int\|null | OPTIONAL | Maximum number of uses; null means unlimited |
| `use_count` | int | Auto | Current usage count; excluded from signing body |
| `can_redelegate` | bool | REQUIRED | Whether the delegate can further delegate |
| `signature` | string | REQUIRED | `ed25519:<base64url-no-padding>` over canonical signing body |

### Token Signing Body

Implementations MUST compute the signing body as canonical JSON over these fields in alphabetical order:

```json
{
  "can_redelegate": false,
  "capabilities": ["ask", "execute"],
  "delegate_did": "did:roar:agent:worker-...",
  "delegator_did": "did:roar:agent:admin-...",
  "expires_at": 1710086400.0,
  "issued_at": 1710000000.0,
  "max_uses": 10,
  "token_id": "tok_a1b2c3d4e5"
}
```

The `use_count` and `signature` fields MUST NOT be included in the signing body. The `capabilities` array MUST be sorted lexicographically before inclusion.

Serialization MUST use the same canonical JSON rules as message signing: `sort_keys=True, separators=(", ", ": ")`.

### Token Verification in Message Handling

When a message arrives with `context.delegation_token`, implementations MUST perform these checks in order:

1. **Parse**: Deserialize the token from `context["delegation_token"]`. If malformed, return error with HTTP 400.
2. **Bind check**: `token.delegate_did` MUST equal `msg.from_identity.did`. If not, return `"delegation_token_unauthorized"` with HTTP 401.
3. **Expiry check**: If `token.expires_at` is set and `time.now() > token.expires_at`, return `"delegation_token_exhausted"` with HTTP 401.
4. **Use-count check**: Atomically increment `use_count`. If `token.max_uses` is set and `use_count > max_uses`, return `"delegation_token_exhausted"` with HTTP 401. Implementations MUST use atomic operations (e.g., Redis Lua script) to prevent race conditions.
5. **Key resolution**: Resolve the delegator's Ed25519 public key from a trusted source (DID document, trusted directory). Implementations MUST NOT use any key supplied in the message body. If resolution fails, return `"delegation_unverifiable"` with HTTP 503.
6. **Signature verification**: Verify the Ed25519 signature over the canonical signing body using the resolved public key. If verification fails, return `"invalid_delegation_signature"` with HTTP 401.

Only after ALL checks pass SHOULD the message be dispatched to intent handlers.

### Re-delegation

If `can_redelegate` is `true`, the delegate MAY issue a new delegation token to a third party. The new token's capabilities MUST be a subset of the parent token's capabilities. If the parent token has `can_redelegate: false`, attempts to re-delegate MUST be rejected.

---

## Rate Limiting (Normative)

Implementations SHOULD enforce rate limiting on message endpoints. When rate-limited, the server MUST return HTTP 429 Too Many Requests with:

```json
{
  "error": "rate_limited",
  "message": "Rate limit exceeded. Retry after {seconds}s."
}
```

The response MUST include a `Retry-After` header with the number of seconds until the next request will be accepted.

Implementations MAY include these headers on all responses:
- `X-RateLimit-Limit-Minute` — maximum requests per minute
- `X-RateLimit-Remaining-Minute` — remaining requests this minute

---

## Request Body Size Limits (Normative)

Message endpoints MUST enforce a maximum request body size of **1 MiB**. Requests exceeding this limit MUST be rejected with HTTP 413 Payload Too Large.

---

## Replay Protection (Normative)

Implementations MUST maintain a deduplication cache keyed by message `id`. Duplicate messages within the replay window MUST be rejected with HTTP 409 Conflict:

```json
{
  "error": "duplicate_message",
  "detail": "Message already processed."
}
```

The cache MUST retain entries for at least 600 seconds. Implementations MAY use bounded LRU eviction (RECOMMENDED: 10,000 entries) to limit memory usage.

---

## Error Response Codes

| Code | Error | When |
|------|-------|------|
| 400 | `invalid_message` | Malformed request body |
| 400 | `verification_failed` | StrictMessageVerifier rejection |
| 401 | `signature_invalid` | HMAC/Ed25519 verification failed |
| 401 | `no_signing_secret` | Server has no signing secret configured (fail-closed) |
| 401 | `delegation_token_unauthorized` | Delegate DID mismatch |
| 401 | `delegation_token_exhausted` | Token expired or max uses reached |
| 401 | `invalid_delegation_signature` | Token signature invalid |
| 409 | `duplicate_message` | Replay detected |
| 413 | `request_too_large` | Body exceeds size limit |
| 429 | `rate_limited` | Too many requests |
| 503 | `delegation_unverifiable` | Cannot resolve delegator key |

---

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
