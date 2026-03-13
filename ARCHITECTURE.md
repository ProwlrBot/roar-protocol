# ROAR Protocol Architecture

**Real-time Open Agent Runtime — Layer Model and Intellectual Foundations**

---

## The Five-Layer Model

ROAR is structured as a layered protocol stack, directly inspired by the OSI
Reference Model (ISO/IEC 7498, 1984). Each layer provides services to the
layer above it and consumes services from the layer below. A ROAR
implementation may use any contiguous bottom-up subset of layers.

```
┌─────────────────────────────────────────────────────────┐
│  Layer 5: Stream                                        │
│  Real-time event pub/sub — SSE, WebSocket               │
│  EventBus, StreamEvent, AIMD backpressure, dedup        │
├─────────────────────────────────────────────────────────┤
│  Layer 4: Exchange                                      │
│  Unified message format, signing, intent dispatch       │
│  ROARMessage, MessageIntent, HMAC-SHA256, Ed25519       │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Connect                                       │
│  Transport negotiation and session management           │
│  stdio, HTTP, WebSocket, gRPC, ConnectionConfig         │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Discovery                                     │
│  Agent registration, capability search, federation      │
│  AgentDirectory, AgentCard, ROARHub, DiscoveryCache     │
├─────────────────────────────────────────────────────────┤
│  Layer 1: Identity                                      │
│  W3C DID-based agent identity and capability declaration│
│  AgentIdentity, DIDDocument, did:key, did:web           │
└─────────────────────────────────────────────────────────┘
```

### How the layers map to OSI

| OSI Layer | OSI Name | ROAR Layer | ROAR Concern |
|:---------:|:---------|:----------:|:-------------|
| 7 | Application | 5 — Stream | What agents *do* with events |
| 6 | Presentation | 4 — Exchange | Wire encoding, signing, serialization |
| 5 | Session | 3 — Connect | Connection config, auth negotiation |
| 4 | Transport | 3 — Connect | Transport selection (HTTP vs WS vs stdio) |
| 3 | Network | 3 — Connect | Routing to agent endpoints |
| 2 | Data Link | — | (handled by underlying network) |
| 1 | Physical | — | (handled by underlying network) |
| — | *(no OSI equiv)* | 1 — Identity | Agent identity, keys, DIDs |
| — | *(no OSI equiv)* | 2 — Discovery | Agent registration and capability search |

OSI predates agents, so it has no concept of **who is communicating** (Layer 1)
or **how to find who to communicate with** (Layer 2). ROAR adds both below the
transport layer, making agent identity a first-class concern — not an
application-level afterthought.

---

## Layer 1 — Identity

**Problem:** In OSI, IP addresses identify machines, not entities. In agent
systems, you need to know *who* an agent is, *what* it can do, and whether you
should trust it — before any message is sent.

**Solution:** W3C Decentralized Identifiers (DIDs).

```
did:roar:agent:planner-a1b2c3d4e5f6g7h8
  ^     ^       ^       ^
  |     |       |       unique suffix (random hex)
  |     |       slug (from display_name)
  |     agent_type (agent|tool|human|ide)
  DID method
```

Every ROAR agent has an `AgentIdentity` with a DID, display name, agent type,
capabilities list, version, and optional Ed25519 public key.

An `AgentCard` extends identity with a description, skills list, communication
channels, endpoint URLs, and formal capability declarations. An AgentCard is
an agent's "business card" — it's what gets published to a discovery directory.

### DID Methods

ROAR supports three DID methods:

| Method | Format | Use case |
|:-------|:-------|:---------|
| `did:roar:` | `did:roar:<type>:<slug>-<hex>` | Default, ROAR-native agents |
| `did:key:` | `did:key:z6Mk<base58>` | Ephemeral agents (no registry needed) |
| `did:web:` | `did:web:example.com:agents:planner` | Persistent, domain-bound agents |

`did:key` is the most decentralized: the DID *is* the public key, encoded with
a multicodec prefix (`0xed01` for Ed25519) and base58. No server lookup
required. The DID resolves to a DID Document that can be reconstructed from
the key bytes alone.

### DID Documents

A DID Document is a W3C JSON-LD structure that describes an agent's:
- Verification methods (public keys)
- Authentication references
- Service endpoints (where to reach the agent)

```json
{
  "@context": [
    "https://www.w3.org/ns/did/v1",
    "https://w3id.org/security/suites/ed25519-2020/v1"
  ],
  "id": "did:roar:agent:planner-a1b2c3d4",
  "controller": "did:roar:agent:planner-a1b2c3d4",
  "verificationMethod": [{
    "id": "did:roar:agent:planner-a1b2c3d4#key-1",
    "type": "Ed25519VerificationKey2020",
    "controller": "did:roar:agent:planner-a1b2c3d4",
    "publicKeyMultibase": "f<hex-encoded-public-key>"
  }],
  "authentication": ["did:roar:agent:planner-a1b2c3d4#key-1"],
  "service": [{
    "id": "did:roar:agent:planner-a1b2c3d4#svc-http",
    "type": "ROARMessaging",
    "serviceEndpoint": "https://agents.example.com/planner"
  }]
}
```

### Graduated Autonomy

Agents operate at one of four autonomy levels:

```
WATCH      → Agent can observe but cannot act
GUIDE      → Agent can suggest; human must approve each action
DELEGATE   → Agent can act on specifically delegated capabilities
AUTONOMOUS → Agent can act freely within its declared capabilities
```

`CapabilityDelegation` manages runtime grants. `DelegationToken` encodes
cryptographic grants that travel with messages and can be verified offline.

---

## Layer 2 — Discovery

**Problem:** How does Agent A find Agent B when it only knows B's capability,
not its address?

**Solution:** A hierarchical discovery system with three tiers:

```
Tier 1 — Local registry    (in-process AgentDirectory or SQLiteAgentDirectory)
Tier 2 — Hub federation    (ROARHub instances syncing via push/pull)
Tier 3 — DNS-based         (IETF BANDAID, future — TXT records per domain)
```

An `AgentDirectory` maps DID → `DiscoveryEntry` (which contains the full
`AgentCard`). `AgentCard.skills` and `AgentCard.identity.capabilities` enable
capability-based search: "find me any agent that can do `code-review`".

`ROARHub` adds REST endpoints (`/roar/agents`, `/roar/federation/sync`) that
allow hub instances to exchange their agent lists. A hub in London can
discover an agent registered on a hub in Tokyo.

`DiscoveryCache` provides a TTL+LRU caching layer in front of any directory.
Cache miss falls through to the hub; cache hit returns in O(1).

`SQLiteAgentDirectory` makes the local registry persistent — agents survive
restarts without re-registering.

---

## Layer 3 — Connect

**Problem:** Agents run in wildly different environments — subprocess, remote
server, edge device, local IDE. No single transport works for all.

**Solution:** A `ConnectionConfig` specifies *how* to reach an agent,
independent of *what* to say to it (Layer 4).

```python
config = ConnectionConfig(
    transport=TransportType.HTTP,
    url="https://agents.example.com/planner/roar/message",
    auth_method="hmac",
    secret="shared-secret",
    timeout_ms=30000,
)
```

Transport auto-selection prefers WebSocket (for bidirectional streaming) over
HTTP (for request/response) over stdio (for subprocess agents). The endpoints
declared in an agent's `AgentCard` drive auto-selection.

### FastAPI Router

`create_roar_router()` mounts ROAR onto an existing FastAPI application with
zero extra infrastructure:

```
POST /roar/message   → single message, single response
WS   /roar/ws        → bidirectional streaming
GET  /roar/events    → SSE fan-out
GET  /roar/health    → health check
```

The router includes token-bucket rate limiting, Bearer auth for WebSocket/SSE,
and replay protection via an in-memory idempotency guard.

---

## Layer 4 — Exchange

**Problem:** Every protocol (MCP, A2A, ACP, stdio, gRPC) has its own message
format. An agent speaking to multiple downstream protocols needs N serializers.

**Solution:** One message format with seven intents. Adapters translate at the
boundaries.

```
ROARMessage
  roar: "1.0"        protocol version
  id:   "msg_..."    unique message ID
  from: AgentIdentity
  to:   AgentIdentity
  intent: execute | delegate | update | ask | respond | notify | discover
  payload: {}        intent-specific content
  context: {}        session, trace, delegation tokens
  auth:   {}         signature + timestamp
  timestamp: float
```

### The 7 Intents (and when to use each)

| Intent | Sender → Receiver | When |
|:-------|:-----------------|:-----|
| `execute` | Agent → Tool | Call a tool or command |
| `delegate` | Agent → Agent | Hand off a task to a peer |
| `update` | Agent → IDE/Human | Report progress on an ongoing task |
| `ask` | Agent → Human | Request input, approval, or clarification |
| `respond` | Any → Any | Reply to any of the above |
| `notify` | Any → Any | One-way broadcast (no reply expected) |
| `discover` | Any → Directory | Query for agents by capability |

### Signing

HMAC-SHA256 over a canonical JSON body covering all security-relevant fields:

```python
body = json.dumps({
    "id": msg.id,
    "from": msg.from_identity.did,
    "to": msg.to_identity.did,
    "intent": msg.intent,
    "payload": msg.payload,
    "context": msg.context,
    "timestamp": msg.auth["timestamp"],  # set before signing
}, sort_keys=True)

signature = "hmac-sha256:" + hmac.new(secret, body, sha256).hexdigest()
```

`sort_keys=True` ensures deterministic output across languages. The timestamp
is included *in the signing body* (not just in `auth`) to prevent timestamp
stripping attacks. Replay protection rejects messages older than 5 minutes.

### Ed25519

For cross-organization trust where HMAC shared secrets are impractical:

```
Agent signs with private key → includes public key in message auth
Receiver verifies using public key from sender's AgentIdentity or DID Document
```

Ed25519 (RFC 8032, NIST FIPS 186-5) uses 32-byte keys and 64-byte signatures.
Both the `cryptography` (Python) and Node.js built-in `crypto` (TypeScript)
implementations are conformant.

### Protocol Adapters

Three adapters provide bidirectional translation at the boundaries:

```
External protocol ←→ Adapter ←→ ROARMessage

MCP (JSON-RPC 2.0 tool calls) ←→ MCPAdapter
A2A (agent task lifecycle)    ←→ A2AAdapter
ACP (IDE session/messages)    ←→ ACPAdapter
```

`detect_protocol()` sniffs an incoming JSON body and returns which adapter to
use — ROAR servers can accept all three protocols on a single endpoint.

---

## Layer 5 — Stream

**Problem:** Agents generate continuous, real-time events (reasoning traces,
tool calls, progress updates) that need to be observed by humans, IDEs, and
other agents without polling.

**Solution:** An `EventBus` with typed `StreamEvent` objects, delivered via
SSE or WebSocket with backpressure control.

```
EventBus
  ↓ publishes to
Subscription (async-iterable, filtered)
  ↓ consumed by
SSE /roar/events  ← browser, IDE, dashboard
WS  /roar/ws      ← bidirectional agent-to-agent
```

### AIMD Backpressure

ROAR uses the same congestion control algorithm as TCP (Additive Increase /
Multiplicative Decrease, Jacobson 1988):

```
On success delivery:  rate += 10 events/sec  (linear growth)
On dropped event:     rate *= 0.5            (exponential backoff)
```

This prevents a fast publisher from overwhelming a slow consumer while
maximizing throughput when the consumer can keep up.

### Idempotency Guard

SSE and WebSocket transports use at-least-once delivery. `IdempotencyGuard`
prevents duplicate processing using an LRU-bounded, TTL-expiring seen-key set.

---

## Prior Art and References

### Specifications

| Spec | Version | Relevance |
|:-----|:--------|:----------|
| [OSI Reference Model](https://www.iso.org/standard/20269.html) | ISO/IEC 7498 (1984) | The original layered architecture model |
| [W3C DID Core](https://www.w3.org/TR/did-core/) | v1.0 (July 2022) | Layer 1 identity foundation |
| [W3C VC Data Model](https://www.w3.org/TR/vc-data-model-2.0/) | v2.0 (March 2025) | Credential issuance over DIDs |
| [DIDComm Messaging](https://identity.foundation/didcomm-messaging/spec/) | v2.1 (DIF) | DID-based signed envelopes (inspires Layer 4 signing) |
| [did:key Method](https://w3c-ccg.github.io/did-method-key/) | W3C CCG | Layer 1 ephemeral identity |
| [did:web Method](https://w3c-ccg.github.io/did-method-web/) | W3C CCG | Layer 1 DNS-bound identity |
| [MCP Specification](https://spec.modelcontextprotocol.io/) | v2025-11-25 | Tool integration (ROAR MCPAdapter) |
| [A2A Protocol](https://github.com/google/A2A) | v0.3.0 | Agent task delegation (ROAR A2AAdapter) |
| [ACP Specification](https://github.com/agntcy/acp-spec) | v0.2.3 | IDE↔agent sessions (ROAR ACPAdapter) |
| [IETF BANDAID](https://datatracker.ietf.org/doc/draft-mozleywilliams-dnsop-dnsaid/) | Draft | DNS-based agent discovery (future Layer 2) |
| [RFC 2104](https://www.rfc-editor.org/rfc/rfc2104) | IETF | HMAC algorithm (Layer 4 signing) |
| [RFC 8032](https://www.rfc-editor.org/rfc/rfc8032) | IETF | Ed25519 algorithm (Layer 1 keys) |
| [NIST FIPS 186-5](https://csrc.nist.gov/publications/detail/fips/186/5/final) | NIST (2023) | Ed25519 federal approval |
| [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455) | IETF | WebSocket protocol (Layer 3 transport) |
| [Jacobson 1988](https://dl.acm.org/doi/10.1145/52324.52356) | SIGCOMM | AIMD congestion control (Layer 5 backpressure) |

### Standards Bodies

| Body | Relevance |
|:-----|:---------|
| [AAIF — Agentic AI Foundation](https://agenticai.foundation) | Linux Foundation project governing MCP, A2A, and related agentic protocols. ROAR target for bridge protocol recognition. |
| [W3C DID Working Group](https://www.w3.org/groups/wg/did/) | Governs DID Core. ROAR Layer 1 must remain DID Core-compliant. |
| [Decentralized Identity Foundation (DIF)](https://identity.foundation) | Governs DIDComm, did:key, did:web, and credential exchange specs. |
| [IETF](https://www.ietf.org) | Governs HTTP, WebSocket, HMAC, Ed25519, and the emerging BANDAID draft. |
| [W3C WebApps WG](https://www.w3.org/groups/wg/webapps/) | Governs SSE (Server-Sent Events), used in Layer 5. |

### Academic Papers

| Paper | Why it matters |
|:------|:--------------|
| Jacobson, V. (1988). "Congestion Avoidance and Control." *ACM SIGCOMM*. | Foundation for AIMD backpressure in Layer 5. |
| Bernstein, D.J. et al. (2011). "High-speed high-security signatures." *CHES 2011*. | Designed Ed25519. |
| Nakamoto, S. (2008). "Bitcoin: A Peer-to-Peer Electronic Cash System." | Popularized self-sovereign identity via public key cryptography — intellectual ancestor of DIDs. |
| Hardt, D. (2012). "The OAuth 2.0 Authorization Framework." *RFC 6749*. | The delegation pattern ROAR's `DelegationToken` is loosely derived from. |

---

## Design Principles

1. **Layer independence.** A Layer 3 transport doesn't know what the payload
   means. A Layer 4 message doesn't care which transport delivered it.

2. **The spec is the authority.** The wire format is defined once. All SDKs
   conform to it, not the other way around.

3. **Backward compatibility via adapters.** ROAR doesn't deprecate MCP or A2A.
   It provides adapters so existing infrastructure keeps working.

4. **No required infrastructure.** An agent can implement just Layer 1
   (identity) and communicate over stdio without a discovery hub, signing
   secret, or streaming bus.

5. **Cryptographic proofs, not trust hierarchies.** Identity is proven by
   signature, not by membership in a registry. Any agent can verify any other
   agent's identity with only their public key.

6. **Minimal dependencies.** The Python SDK requires only `pydantic`. Every
   other feature (Ed25519, WebSocket, FastAPI) is an optional extra.
