# ROAR Protocol — AAIF Standards Submission Package

**Submitted to:** Agentic AI Foundation (AAIF) Technical Committee
**Requested Status:** Bridge Protocol Standard
**Date:** 2026-03-17
**Specification Version:** 0.3.0
**Submitted by:** [@kdairatchi](https://github.com/kdairatchi)

---

## 1. Executive Summary

The **Routable Open Agent Runtime (ROAR)** is a five-layer protocol that bridges MCP, A2A, and ACP into a unified agent communication framework. Rather than replacing these protocols, ROAR provides the missing connective tissue: a single message format, cryptographic identity layer, and discovery mechanism that allows MCP tool servers, A2A agent networks, and ACP IDE integrations to interoperate without custom glue code.

ROAR addresses a gap in the current AAIF protocol landscape. MCP excels at tool integration. A2A excels at agent-to-agent task delegation. But no standard exists for an agent that needs to call an MCP tool, delegate to an A2A peer, update an IDE via ACP, and stream progress to a dashboard — all within the same session, with a unified identity and cryptographic audit trail. ROAR is that standard.

We submit ROAR for recognition as a **bridge protocol standard** under the AAIF Technical Committee, complementing MCP and A2A within the AAIF umbrella.

---

## 2. Protocol Overview

### 2.1 The Five-Layer Model

ROAR is structured as a layered protocol stack inspired by the OSI Reference Model:

```
Layer 5: Stream     — Real-time event pub/sub (SSE, WebSocket)
Layer 4: Exchange   — Unified message format, signing, verification
Layer 3: Connect    — Transport negotiation (stdio, HTTP, WS, gRPC)
Layer 2: Discovery  — Agent registration, capability search, federation
Layer 1: Identity   — W3C DID-based agent identity, capability declaration
```

Each layer builds on the one below. Implementations may use any contiguous bottom-up subset — an agent can implement just Layer 1 (identity) and Layer 2 (discovery) without requiring the full stack.

### 2.2 The Seven Intents

All ROAR communication uses a single `ROARMessage` format with seven intent types:

| Intent | Direction | Purpose |
|:-------|:---------|:--------|
| `execute` | Agent to Tool | Invoke a tool or command (maps to MCP tool calls) |
| `delegate` | Agent to Agent | Hand off a task to a peer (maps to A2A task delegation) |
| `update` | Agent to IDE/Human | Report progress on an ongoing task |
| `ask` | Agent to Human | Request input, approval, or clarification |
| `respond` | Any to Any | Reply to any message |
| `notify` | Any to Any | One-way notification (no reply expected) |
| `discover` | Any to Directory | Find agents by capability |

### 2.3 Identity Model

Agents identify themselves using W3C Decentralized Identifiers (DIDs):

```
did:roar:agent:planner-a1b2c3d4e5f6g7h8
```

Three DID methods are supported:
- `did:roar:` — ROAR-native, generated locally
- `did:key:` — Self-sovereign, the DID is the public key (no registry needed)
- `did:web:` — DNS-bound, for persistent organizational identities

Agent identity is a first-class protocol concern, not an application-level afterthought. Every message carries the sender and receiver identity, every message is signed, and every signature is verifiable using only the sender's public key.

### 2.4 Security Model

- **Message signing:** HMAC-SHA256 (symmetric) and Ed25519 (asymmetric) over canonical JSON
- **Replay protection:** 300-second timestamp window plus message ID deduplication (600-second nonce store)
- **Transport encryption:** TLS required for HTTP and WebSocket in production
- **Audit trail:** Tamper-evident hash chain with Ed25519 signatures over metadata
- **Graduated autonomy:** Four levels (WATCH, GUIDE, DELEGATE, AUTONOMOUS) with cryptographic delegation tokens

---

## 3. Differentiators

### 3.1 Comparison with MCP

| Dimension | MCP | ROAR |
|:----------|:----|:-----|
| Primary focus | Tool integration (JSON-RPC 2.0) | Unified agent communication |
| Identity model | Server-defined, no standard identity | W3C DIDs with cryptographic proof |
| Message signing | Not specified | HMAC-SHA256 and Ed25519, mandatory |
| Agent discovery | Server-side tool listing | Federated directory with capability search |
| Agent-to-agent | Not supported | Native (delegate intent) |
| Audit trail | Not specified | Tamper-evident hash chain |
| Streaming | SSE-based notifications | EventBus with 11 event types, AIMD backpressure |

ROAR does not replace MCP. The `MCPAdapter` translates MCP tool calls to ROAR `execute` messages bidirectionally. An MCP server can be registered as a ROAR tool agent and discovered by any ROAR agent without modification to the MCP server.

### 3.2 Comparison with A2A

| Dimension | A2A | ROAR |
|:----------|:----|:-----|
| Primary focus | Agent-to-agent task lifecycle | Unified agent communication |
| Identity model | Agent Cards with skills/capabilities | W3C DIDs with Agent Cards (compatible) |
| Message format | Task-based (send, get, cancel) | Intent-based (7 intents covering all patterns) |
| Tool integration | Not specified | Native (execute intent, MCP bridge) |
| Federation | Not specified | Hub-based with push/pull sync |
| Signing | Not specified | HMAC-SHA256 and Ed25519 |
| IDE integration | Not specified | Native (update, ask intents; ACP bridge) |

ROAR does not replace A2A. The `A2AAdapter` translates A2A task operations to ROAR `delegate` messages bidirectionally. An A2A agent can participate in ROAR sessions without protocol-level changes, with the original A2A protocol preserved in the message context.

### 3.3 What ROAR Adds

ROAR bridges the gap between MCP and A2A by providing:

1. **Unified identity:** A single DID identifies an agent across MCP, A2A, and ACP interactions
2. **Unified signing:** One cryptographic model (HMAC or Ed25519) secures all message types
3. **Protocol bridging:** `MCPAdapter`, `A2AAdapter`, and `ACPAdapter` translate at the boundaries
4. **Federated discovery:** Agents registered on different hubs can discover each other
5. **Cryptographic audit trail:** Every interaction is logged in a tamper-evident chain
6. **Graduated autonomy:** Fine-grained control over what agents can do, with cryptographic delegation tokens

---

## 4. Interoperability Proof

### 4.1 Working MCP-to-A2A Bridge

ROAR includes production-quality bidirectional adapters:

**MCP to ROAR:**
```python
roar_msg = MCPAdapter.mcp_to_roar("read_file", {"path": "src/main.py"}, agent)
# Creates a ROARMessage with intent=execute, preserving MCP tool name and params
```

**ROAR to A2A:**
```python
a2a_task = A2AAdapter.roar_to_a2a(roar_msg)
# Converts to A2A task format, preserving original protocol in context.protocol
```

**A2A to ROAR:**
```python
roar_msg = A2AAdapter.a2a_task_to_roar(task, sender, receiver)
# Creates a ROARMessage with intent=delegate from an A2A task
```

### 4.2 Test Coverage

The ROAR Protocol test suite includes 356 tests covering:

- Wire format serialization and deserialization
- HMAC-SHA256 and Ed25519 signing and verification
- Replay protection (timestamp window, nonce deduplication, future skew)
- MCP adapter round-trip fidelity
- A2A adapter round-trip fidelity
- Agent directory registration, lookup, and capability search
- Hub federation sync
- Audit log chain integrity and verification
- StrictMessageVerifier policy enforcement (positive and negative cases)
- Cross-SDK conformance (Python and TypeScript produce identical wire output)

### 4.3 Conformance Testing

The TypeScript SDK passes 30/30 cross-SDK conformance checks, verifying that:
- Both SDKs produce identical canonical JSON for the same message
- Both SDKs generate compatible HMAC-SHA256 signatures
- Both SDKs generate compatible Ed25519 signatures
- Wire format is interchangeable between implementations

---

## 5. Implementation Maturity

### 5.1 SDK Status

| SDK | Version | Status | Layers | Notes |
|:----|:--------|:-------|:-------|:------|
| Python (`roar-sdk`) | 0.3.2 | Complete | All 5 layers | RedisTokenStore, AgentCard attestation |
| TypeScript (`@roar-protocol/sdk`) | 0.3.2 | Complete | All 5 layers | ROARHub, signAgentCard/verifyAgentCard, RedisTokenStore |

Both SDKs are at feature parity:
- Identity: DID generation (`did:roar:`, `did:key:`, `did:web:`), AgentIdentity, AgentCard
- Discovery: In-memory directory, hub-based directory, federation sync
- Connect: HTTP, WebSocket, stdio transports with configurable auth
- Exchange: ROARMessage with 7 intents, HMAC-SHA256, Ed25519, StrictMessageVerifier
- Stream: EventBus with 11 event types, SSE delivery, AIMD backpressure

### 5.2 Specification Completeness

| Artifact | Status |
|:---------|:-------|
| Protocol specification (ROAR-SPEC.md) | Complete — 5 layers, 7 intents, wire format, signing, security |
| Architecture document (ARCHITECTURE.md) | Complete — layer model, OSI mapping, design principles, references |
| Layer specifications (spec/01-05) | Complete — one document per layer |
| JSON schemas (spec/schemas/) | Complete — agent-identity, agent-card, roar-message, stream-event |
| VERSION.json | Active — semantic versioning with per-layer tracking |
| Security policy (SECURITY.md) | Complete — vulnerability reporting, scope, response timeline |
| Privacy documentation (docs/PRIVACY.md) | Complete — GDPR, SOC 2, HIPAA mapping |
| Compliance matrix (docs/COMPLIANCE-MATRIX.md) | Complete — feature-to-framework mapping |

### 5.3 Dependency Profile

The Python SDK requires only `pydantic` as a mandatory dependency. All other capabilities are optional extras:
- `roar-sdk[ed25519]` — Ed25519 signing (adds `cryptography`)
- `roar-sdk[server]` — FastAPI server (adds `fastapi`, `uvicorn`)
- `roar-sdk[redis]` — Redis token store (adds `redis`)

The TypeScript SDK uses Node.js built-in `crypto` for Ed25519, requiring zero additional dependencies for core functionality.

---

## 6. Adoption Path

### 6.1 ROAR as a Complement to MCP and A2A

ROAR is not a competitor to MCP or A2A. It is the bridge layer that makes them work together:

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  MCP Server  │    │  A2A Agent   │    │  ACP IDE     │
│  (tool host) │    │  (task peer) │    │  (session)   │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       │  MCPAdapter       │  A2AAdapter       │  ACPAdapter
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────┐
│                    ROAR Protocol                     │
│  Layer 5: Stream    — unified event bus              │
│  Layer 4: Exchange  — single message format          │
│  Layer 3: Connect   — transport negotiation          │
│  Layer 2: Discovery — federated agent directory      │
│  Layer 1: Identity  — W3C DID for all agents         │
└─────────────────────────────────────────────────────┘
```

An organization already using MCP for tool integration can adopt ROAR incrementally:

1. **Phase 1:** Wrap existing MCP servers with `MCPAdapter` to give them ROAR identities
2. **Phase 2:** Register MCP tools in a ROAR discovery directory for capability-based search
3. **Phase 3:** Add A2A agents via `A2AAdapter` for cross-agent delegation
4. **Phase 4:** Enable federation across organizational boundaries with hub sync
5. **Phase 5:** Deploy audit logging for compliance

Each phase is independently valuable. No phase requires the subsequent ones.

### 6.2 AAIF Integration Model

Under the AAIF umbrella, ROAR would serve as:

- **The identity standard** for agent systems that span MCP and A2A (W3C DID-based, compatible with both)
- **The bridge protocol** for cross-protocol interoperability (adapters are bidirectional and lossless)
- **The audit standard** for agent interactions (tamper-evident, cryptographically signed, metadata-only)
- **The discovery standard** for federated agent networks (hub-based with DNS-based discovery planned)

ROAR's design principle of "unify, don't replace" aligns with AAIF's mission of fostering interoperability across the agentic AI ecosystem.

---

## 7. Technical Specifications

### 7.1 Core Documents

| Document | Path | Description |
|:---------|:-----|:-----------|
| Protocol Specification | [ROAR-SPEC.md](../ROAR-SPEC.md) | Complete protocol definition: layers, intents, wire format, signing, security |
| Architecture | [ARCHITECTURE.md](../ARCHITECTURE.md) | Layer model, OSI mapping, design principles, prior art |
| Layer 1: Identity | [spec/01-identity.md](../spec/01-identity.md) | DID format, AgentIdentity, AgentCard, DID documents, graduated autonomy |
| Layer 2: Discovery | [spec/02-discovery.md](../spec/02-discovery.md) | AgentDirectory, capability search, federation, caching |
| Layer 3: Connect | [spec/03-connect.md](../spec/03-connect.md) | Transport types, ConnectionConfig, auto-selection, FastAPI router |
| Layer 4: Exchange | [spec/04-exchange.md](../spec/04-exchange.md) | ROARMessage format, 7 intents, signing, verification, adapters |
| Layer 5: Stream | [spec/05-stream.md](../spec/05-stream.md) | StreamEvent, EventBus, AIMD backpressure, idempotency |

### 7.2 JSON Schemas

| Schema | Path | Validates |
|:-------|:-----|:---------|
| Agent Identity | [spec/schemas/agent-identity.json](../spec/schemas/agent-identity.json) | AgentIdentity structure |
| Agent Card | [spec/schemas/agent-card.json](../spec/schemas/agent-card.json) | AgentCard structure |
| ROAR Message | [spec/schemas/roar-message.json](../spec/schemas/roar-message.json) | ROARMessage wire format |
| Stream Event | [spec/schemas/stream-event.json](../spec/schemas/stream-event.json) | StreamEvent wire format |

### 7.3 Version Information

```json
{
  "spec_version": "0.3.0",
  "status": "active",
  "python_sdk": "0.3.2",
  "typescript_sdk": "0.3.2",
  "mcp_bridge": true,
  "a2a_bridge": true
}
```

### 7.4 Wire Format Compatibility

| Protocol | ROAR Version | Backward Compatible |
|:---------|:-------------|:-------------------|
| MCP v2025-11-25 | 0.3.0 | Yes — MCPAdapter bidirectional |
| A2A v0.3.0 | 0.3.0 | Yes — A2AAdapter bidirectional |
| ACP v0.2.3 | 0.3.0 | Partial — ACPAdapter maps operation types |

---

## 8. Community and Governance

### 8.1 Open Source

- **Repository:** [github.com/kdairatchi/roar-protocol](https://github.com/kdairatchi/roar-protocol)
- **License:** MIT
- **Contributions:** Open to all via pull requests
- **Issues:** GitHub Issues for bug reports and feature requests
- **Security:** Responsible disclosure via GitHub Security Advisories (see [SECURITY.md](../SECURITY.md))

### 8.2 Versioning Policy

The specification follows semantic versioning tracked in `spec/VERSION.json`:

- **Patch** (0.3.x): Clarifications, documentation fixes, new examples. No wire format change.
- **Minor** (0.x.0): New optional fields, new event types. Backward compatible.
- **Major** (x.0.0): Breaking changes to wire format or required fields.

Both SDKs track the spec version and maintain backward compatibility within minor versions.

### 8.3 Standards Alignment

ROAR builds on established standards:

| Standard | Body | ROAR Usage |
|:---------|:-----|:-----------|
| DID Core v1.0 | W3C | Layer 1 identity foundation |
| VC Data Model v2.0 | W3C | Credential issuance over DIDs |
| DIDComm Messaging v2.1 | DIF | Inspiration for Layer 4 signed envelopes |
| RFC 2104 (HMAC) | IETF | Layer 4 symmetric signing |
| RFC 8032 (Ed25519) | IETF | Layer 1 keys, Layer 4 asymmetric signing |
| FIPS 186-5 (EdDSA) | NIST | Federal approval for Ed25519 |
| RFC 6455 (WebSocket) | IETF | Layer 3 transport |
| IETF BANDAID | IETF (draft) | Future DNS-based agent discovery |

---

## 9. Requested Status

We request that the AAIF Technical Committee recognize ROAR as a **bridge protocol standard** with the following scope:

1. **Bridge Protocol:** ROAR provides the canonical mechanism for cross-protocol agent communication between MCP, A2A, ACP, and future AAIF-recognized protocols

2. **Identity Standard:** ROAR's W3C DID-based identity layer provides a uniform agent identity model across all AAIF protocols

3. **Audit Standard:** ROAR's tamper-evident audit trail provides a uniform compliance mechanism for agent interactions across all AAIF protocols

### 9.1 Commitments

If recognized, the ROAR project commits to:

- Maintaining backward compatibility with MCP and A2A as those protocols evolve
- Participating in AAIF Technical Committee reviews and interoperability testing
- Adopting AAIF-mandated wire format changes within one minor version cycle
- Publishing conformance test suites for bridge protocol compliance
- Keeping both SDKs (Python, TypeScript) at feature parity with the specification

### 9.2 Roadmap

| Phase | Timeline | Deliverable |
|:------|:---------|:-----------|
| Current (0.3.x) | Active | Full MCP and A2A bridging, Ed25519, federation, audit |
| Phase 2 (0.4.0) | Q2 2026 | ACP bridge completion, Verifiable Credentials integration |
| Phase 3 (0.5.0) | Q3 2026 | gRPC transport (protobuf schema ready), DNS-based discovery (IETF BANDAID) |
| Phase 4 (1.0.0) | Q4 2026 | Stable wire format, AAIF conformance certification |

---

## 10. Contact

- **Repository:** [github.com/kdairatchi/roar-protocol](https://github.com/kdairatchi/roar-protocol)
- **Maintainer:** [@kdairatchi](https://github.com/kdairatchi)
- **Specification:** [ROAR-SPEC.md](../ROAR-SPEC.md)
- **License:** MIT
