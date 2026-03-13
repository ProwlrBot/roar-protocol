# ROAR SDK Roadmap

> Status of Python and TypeScript SDK implementations relative to the spec.

Last updated: 2026-03-13 (TypeScript gaps closed)

---

## Current Status

| Layer | Spec | Python SDK | TypeScript SDK |
|:------|:----:|:----------:|:--------------:|
| 1 — Identity | ✅ | ✅ Complete | ✅ Complete |
| 2 — Discovery | ✅ | ✅ Complete | ⚠️ Partial (no Hub/federation) |
| 3 — Connect | ✅ | ✅ Complete | ✅ Complete |
| 4 — Exchange | ✅ | ✅ Complete | ✅ Complete |
| 5 — Stream | ✅ | ✅ Complete | ✅ Complete |

**Conformance:** Python ✅ 30/30 &nbsp;|&nbsp; TypeScript ✅ 30/30

---

## Python SDK — Feature Matrix

### Layer 1 — Identity

| Feature | Status | Module |
|:--------|:------:|:-------|
| `AgentIdentity` + `did:roar:` DID generation | ✅ | `types.py` |
| `AgentCard`, `AgentCapability` | ✅ | `types.py` |
| W3C DID Document generation | ✅ | `did_document.py` |
| `did:key` ephemeral identities | ✅ | `did_key.py` |
| `did:web` DNS-bound identities | ✅ | `did_web.py` |
| `AutonomyLevel` + `CapabilityDelegation` | ✅ | `autonomy.py` |
| `DelegationToken` (cryptographic, portable) | ✅ | `delegation.py` |
| Ed25519 key generation and signing | ✅ | `signing.py` |

### Layer 2 — Discovery

| Feature | Status | Module |
|:--------|:------:|:-------|
| In-memory `AgentDirectory` | ✅ | `types.py` |
| SQLite-backed persistent directory | ✅ | `sqlite_directory.py` |
| `DiscoveryCache` (TTL + LRU) | ✅ | `discovery_cache.py` |
| `ROARHub` with REST API | ✅ | `hub.py` |
| Hub federation (push/pull sync) | ✅ | `hub.py` |
| DNS-based discovery (BANDAID) | ❌ | future |

### Layer 3 — Connect

| Feature | Status | Module |
|:--------|:------:|:-------|
| HTTP transport | ✅ | `transports/` |
| WebSocket transport | ✅ | `transports/` |
| stdio transport | ✅ | `transports/` |
| FastAPI router (HTTP + WS + SSE) | ✅ | `router.py` |
| Token-bucket rate limiting | ✅ | `router.py` |
| gRPC transport | ❌ | future |

### Layer 4 — Exchange

| Feature | Status | Module |
|:--------|:------:|:-------|
| `ROARMessage` + 7 intents | ✅ | `types.py` |
| HMAC-SHA256 signing + replay protection | ✅ | `types.py` |
| Ed25519 message signing/verification | ✅ | `signing.py` |
| `IdempotencyGuard` (dedup) | ✅ | `dedup.py` |
| MCP adapter | ✅ | `types.py` |
| A2A adapter | ✅ | `types.py` |
| ACP adapter | ✅ | `adapters/acp.py` |
| Protocol auto-detection | ✅ | `adapters/detect.py` |

### Layer 5 — Stream

| Feature | Status | Module |
|:--------|:------:|:-------|
| `EventBus` + `Subscription` + `StreamFilter` | ✅ | `streaming.py` |
| AIMD backpressure | ✅ | `streaming.py` |
| `IdempotencyGuard` for stream dedup | ✅ | `dedup.py` |
| SSE via FastAPI router | ✅ | `router.py` |

---

## TypeScript SDK — Feature Matrix

### Layer 1 — Identity

| Feature | Status | Module |
|:--------|:------:|:-------|
| `AgentIdentity` + `did:roar:` DID generation | ✅ | `types.ts` |
| `AgentCard`, `AgentCapability` | ✅ | `types.ts` |
| Ed25519 key generation and signing | ✅ | `signing.ts` |
| `DelegationToken` (cryptographic) | ✅ | `delegation.ts` |
| W3C DID Document | ❌ | future |
| `did:key` ephemeral identities | ✅ | `did_key.ts` |
| `did:web` DNS-bound identities | ✅ | `did_web.ts` |
| `AutonomyLevel` + `CapabilityDelegation` | ✅ | `autonomy.ts` |

### Layer 2 — Discovery

| Feature | Status | Module |
|:--------|:------:|:-------|
| In-memory `AgentDirectory` | ✅ | `types.ts` |
| SQLite-backed persistent directory | ✅ | `sqlite_directory.ts` |
| `DiscoveryCache` | ✅ | `discovery_cache.ts` |
| Hub federation | ❌ | future |

### Layer 3 — Connect

| Feature | Status | Module |
|:--------|:------:|:-------|
| HTTP transport (`ROARClient`) | ✅ | `client.ts` |
| WebSocket transport (client) | ✅ | `websocket.ts` |
| Native HTTP router (SSE + WS server + rate limit) | ✅ | `router.ts` |
| stdio transport | ✅ | `stdio.ts` |

### Layer 4 — Exchange

| Feature | Status | Module |
|:--------|:------:|:-------|
| `ROARMessage` + 7 intents | ✅ | `types.ts` |
| HMAC-SHA256 signing (`pythonJsonDumps` compatible) | ✅ | `message.ts` |
| Ed25519 signing/verification | ✅ | `signing.ts` |
| Protocol auto-detection | ✅ | `detect.ts` |

### Layer 5 — Stream

| Feature | Status | Module |
|:--------|:------:|:-------|
| `EventBus` + `Subscription` + `StreamFilter` | ✅ | `streaming.ts` |
| SSE via native HTTP router | ✅ | `router.ts` |
| `IdempotencyGuard` | ✅ | `dedup.ts` |
| AIMD backpressure | ✅ | `streaming.ts` |

---

## Conformance

Run the full conformance suite (no install needed):

```bash
# Python
cd python && pip install -e ".[dev]" && pytest tests/conformance/

# TypeScript
node tests/validate_golden.mjs
```

All 30 checks must pass before claiming ROAR compliance.

---

## Next SDK Priorities

### Python (Medium Priority)

1. DNS-based discovery (IETF BANDAID alignment)
2. gRPC transport stub
3. `DelegationToken` use-count enforcement (currently unlimited-use tokens aren't decremented server-side)

### Both SDKs (Low Priority)

1. `did:key` for TypeScript (requires base58 dep or custom encoder)
2. Full AIMD controller for TypeScript streaming (replace drop-oldest with proper rate adaptation)
