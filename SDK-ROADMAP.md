# ROAR SDK Roadmap

> Status of all SDK implementations relative to the spec.

Last updated: 2026-03-17 (cross-terminal release — Go/Rust server+hub, security fixes, conformance tests, deployment, docs)

---

## Current Status

| Layer | Spec | Python SDK | TypeScript SDK | Go SDK | Rust SDK |
|:------|:----:|:----------:|:--------------:|:------:|:--------:|
| 1 — Identity | ✅ | ✅ Complete | ✅ Complete | ✅ Types | ✅ Types |
| 2 — Discovery | ✅ | ✅ Complete | ✅ Complete | ✅ Hub | ✅ Hub |
| 3 — Connect | ✅ | ✅ Complete | ✅ Complete | ✅ HTTP | ✅ HTTP |
| 4 — Exchange | ✅ | ✅ Complete | ✅ Complete | ✅ Signing + Server | ✅ Signing + Server |
| 5 — Stream | ✅ | ✅ Complete | ✅ Complete | — | — |

**Conformance:** Python ✅ 664 tests &nbsp;|&nbsp; TypeScript ✅ 30/30 golden fixtures + 10 unit tests &nbsp;|&nbsp; Go ✅ unit tests &nbsp;|&nbsp; Rust ✅ unit tests

---

## Python SDK — Feature Matrix

### Layer 1 — Identity

| Feature | Status | Module |
|:--------|:------:|:-------|
| `AgentIdentity` + `did:roar:` DID generation | ✅ | `types.py` |
| `AgentCard`, `AgentCapability` | ✅ | `types.py` |
| AgentCard signed attestation | ✅ | `signing.py` |
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
| Hub challenge-response registration | ✅ | `hub_auth.py` |
| Hub federation (push/pull sync) | ✅ | `hub.py` |
| DNS-based discovery (IETF BANDAID) | ✅ | `dns_discovery.py` |

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
| `StrictMessageVerifier` (production receiver) | ✅ | `verifier.py` |
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

### Token Stores

| Store | Use Case | Status |
|:------|:---------|:-------|
| `InMemoryTokenStore` | Single-process, default | ✅ |
| `RedisTokenStore` | Multi-worker, requires `roar-sdk[redis]` | ✅ |

---

## TypeScript SDK — Feature Matrix

### Layer 1 — Identity

| Feature | Status | Module |
|:--------|:------:|:-------|
| `AgentIdentity` + `did:roar:` DID generation | ✅ | `types.ts` |
| `AgentCard`, `AgentCapability` | ✅ | `types.ts` |
| AgentCard signed attestation | ✅ | `signing.ts` |
| Ed25519 key generation and signing | ✅ | `signing.ts` |
| `DelegationToken` (cryptographic) | ✅ | `delegation.ts` |
| W3C DID Document | ✅ | `did_document.ts` |
| `did:key` ephemeral identities | ✅ | `did_key.ts` |
| `did:web` DNS-bound identities | ✅ | `did_web.ts` |
| `AutonomyLevel` + `CapabilityDelegation` | ✅ | `autonomy.ts` |

### Layer 2 — Discovery

| Feature | Status | Module |
|:--------|:------:|:-------|
| In-memory `AgentDirectory` | ✅ | `types.ts` |
| SQLite-backed persistent directory | ✅ | `sqlite_directory.ts` |
| `DiscoveryCache` | ✅ | `discovery_cache.ts` |
| `ROARHub` with REST API | ✅ | `hub.ts` |
| Hub challenge-response registration | ✅ | `hub_auth.ts` |
| Hub federation (sync + export) | ✅ | `hub.ts` |
| DNS-based discovery (IETF BANDAID) | ✅ | `dns_discovery.ts` |

### Layer 3 — Connect

| Feature | Status | Module |
|:--------|:------:|:-------|
| HTTP transport (`ROARClient`) | ✅ | `client.ts` |
| WebSocket transport | ✅ | `websocket.ts` |
| Native HTTP router (SSE + WS + rate limit) | ✅ | `router.ts` |
| stdio transport | ✅ | `stdio.ts` |
| gRPC transport | ❌ | future |

### Layer 4 — Exchange

| Feature | Status | Module |
|:--------|:------:|:-------|
| `ROARMessage` + 7 intents | ✅ | `types.ts` |
| HMAC-SHA256 signing (`pythonJsonDumps` compatible) | ✅ | `message.ts` |
| Ed25519 signing/verification | ✅ | `signing.ts` |
| `StrictMessageVerifier` (production receiver) | ✅ | `verifier.ts` |
| Protocol auto-detection | ✅ | `detect.ts` |

### Layer 5 — Stream

| Feature | Status | Module |
|:--------|:------:|:-------|
| `EventBus` + `Subscription` + `StreamFilter` | ✅ | `streaming.ts` |
| SSE via native HTTP router | ✅ | `router.ts` |
| `IdempotencyGuard` | ✅ | `dedup.ts` |
| AIMD backpressure | ✅ | `streaming.ts` |

### Token Stores

| Store | Use Case | Status |
|:------|:---------|:-------|
| `InMemoryTokenStore` | Single-process, default | ✅ |
| `RedisTokenStore` | Multi-worker, requires `ioredis` | ✅ |

---

## Conformance

```bash
# Python — full test suite
cd python && pip install -e ".[dev]" && pytest ../tests/ -q

# TypeScript — unit tests + golden fixtures
cd ts && npm test
node tests/validate_golden.mjs
```

All checks must pass before claiming ROAR compliance.

---

## What's Still Ahead

All four SDKs are feature-complete for the current spec (v0.3.0). All 32 roadmap features are implemented. Remaining work is spec extensions or transport additions:

- **gRPC transport** — protobuf schema exists (`spec/protobuf/roar.proto`); Python/TypeScript streaming semantics still needed
- **QUIC/HTTP3 transport** — future
- **AAIF submission** — register ROAR as a bridge protocol at the AAIF technical committee
- **Federation per-card signing** — planned for v0.4 spec (see THREAT-MODEL.md §5.5)
