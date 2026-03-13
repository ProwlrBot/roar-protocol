# Phase 2: Technical Deep Dives

**Project ROAR — Research Plan, Phase 2**
Version: 1.0 | Status: Draft

---

## Section 1: DID Method Comparison for Layer 1 Identity

ROAR uses W3C Decentralized Identifiers (DIDs) as the foundation of agent identity. The choice of DID method determines resolution speed, infrastructure requirements, and suitability for ephemeral agent instances.

### Candidates

| Property | did:key | did:web | did:ion |
|---|---|---|---|
| **Resolution** | Instant (no network) | DNS + HTTP (~50–200ms) | 2–10s (Bitcoin anchor) |
| **Infrastructure** | None | Web server + domain | Bitcoin/ION node |
| **Decentralization** | Full (self-contained) | Partial (DNS-dependent) | High (ledger-anchored) |
| **Key rotation** | ❌ Not supported | ✅ Update hosted JSON | ✅ Full rotation |
| **Revocation** | ❌ Not supported | ✅ Delete/update JSON | ✅ Deactivate DID |
| **Ephemeral agents** | ✅ Ideal | ⚠️ Requires domain | ❌ Too heavy |
| **Persistent agents** | ⚠️ No rotation | ✅ Stable + updatable | ✅ Strongest model |
| **Human-readable** | ❌ Base58 blob | ✅ Domain-based | ❌ Long hash |
| **W3C status** | Specification | Specification | Community Draft |

### Recommendation

**Default: `did:key` for ephemeral agents, `did:web` for persistent agents.**

ROAR generates `did:roar:` identifiers today (a custom method using UUID slugs). For the next major version, ROAR should adopt a two-tier approach:

- **Ephemeral agents** (scan workers, CI runners, per-task tool wrappers): use `did:key` — instant resolution, zero infrastructure, disposable. The full public key is encoded in the DID itself.
- **Persistent agents** (team bots, hub nodes, long-running assistants, marketplace agents): use `did:web` — stable domain-anchored identity at `https://agent.example.com/.well-known/did.json`. Supports key rotation by updating the hosted document.
- **Reject `did:ion` as a default** — the 2–10 second cold-resolve latency is incompatible with real-time agent interactions. It could be offered as an opt-in for high-assurance scenarios.

The current `did:roar:` format should be treated as a development shorthand and migrated to `did:key`/`did:web` in v1.0 of the spec.

---

## Section 2: Discovery Layer Architecture

Discovery is the least-solved problem in agent interoperability. ROAR needs a layered resolver that works for local development, enterprise LAN, and cross-organization federation without forcing a single infrastructure choice.

### Option Comparison

| Approach | Latency | Infra needed | Privacy | Federation | Best for |
|---|---|---|---|---|---|
| **In-process cache** | ~0ms | None | Full | ❌ | Local dev, testing |
| **mDNS / DNS-SD** | ~5–50ms | None (LAN) | LAN-only | ❌ | Local network agents |
| **DNS SVCB (BANDAID)** | ~50–200ms | DNS zone control | Public | ✅ | Public/enterprise agents |
| **ROAR Hub (HTTP)** | ~20–100ms | Hub server | Configurable | ✅ | Managed deployments |
| **libp2p DHT** | ~200–2000ms | Bootstrap nodes | Good | ✅ | Decentralized/P2P |

### Four-Tier Layered Resolver (Recommendation)

ROAR should implement discovery as a cascading resolver — fast paths first, falling back to slower but more universal approaches:

```
Tier 1: In-process AgentDirectory (already implemented)
  → Check local cache first, ~0ms

Tier 2: LAN via mDNS/DNS-SD
  → Announce: _roar._tcp.local. TXT "did=did:key:..."
  → Works on same-network agents without any configuration
  → 5–50ms resolution

Tier 3: ROAR Hub federation (HTTP)
  → GET /roar/agents?capability=recon
  → Hubs sync with each other via /roar/federation/sync
  → Each DiscoveryEntry carries hub_url for attribution
  → 20–100ms resolution

Tier 4: libp2p DHT (fallback)
  → For cross-organizational P2P discovery without a hub
  → Bootstrap via well-known nodes
  → 200–2000ms, not suitable for latency-sensitive paths
```

### DNS-Based Discovery (IETF BANDAID Alignment)

The IETF BANDAID (Brokered Agent Network for DNS AI Discovery) draft proposes using SVCB/HTTPS DNS records for agent discovery. ROAR should align with this for public agents:

```dns
; A ROAR hub announces its presence at:
_roar._tcp.example.com. IN SVCB 1 hub.example.com. (
    alpn="roar-1.0"
    port=443
)

; Individual agents announce capabilities via TXT:
_agents.example.com. IN TXT "did=did:web:example.com capabilities=recon,scan"
```

This lets any ROAR agent bootstrap discovery by querying `_roar._tcp.<domain>` — no out-of-band configuration required for agents in known organizations.

---

## Section 3: Transport Protocol Matrix for Layers 3 & 5

Layer 3 (Connect) handles transport negotiation. Layer 5 (Stream) requires real-time event delivery. The right transport depends on the deployment context.

### Comparison Matrix

| Transport | Latency | Direction | Browser | Binary | NAT | Complexity |
|---|---|---|---|---|---|---|
| **HTTP/REST** | ~10–100ms | Request/response | ✅ | ⚠️ | ✅ | Low |
| **SSE** | ~10–50ms | Server→Client | ✅ | ❌ | ✅ | Low |
| **WebSocket** | ~1–10ms | Full-duplex | ✅ | ✅ | ✅ | Medium |
| **WebTransport** | ~0.5–5ms | Full-duplex | ✅ (Chrome/FF) | ✅ | ✅ | High |
| **gRPC** | ~1–5ms | Streaming | ❌ (needs proxy) | ✅ | ✅ | High |
| **stdio** | ~0ms | Full-duplex | ❌ | ✅ | N/A | Minimal |

### Auto-Selection Rules (Recommendation)

ROAR's `ConnectionConfig` should include a `preferred_transports` list. The SDK auto-selects based on context:

```
Local subprocess (MCP-style)    → stdio
Same-machine HTTP               → HTTP (localhost, no TLS overhead)
Browser agent (web)             → WebSocket (full-duplex) or SSE (server-push only)
Cross-machine general           → WebSocket
High-throughput enterprise      → gRPC
Ultra-low-latency peer mesh     → WebTransport (when available)
```

### SSE as First-Class Transport

The current spec defines `TransportType.HTTP` but SSE (Server-Sent Events) is a distinct transport pattern — one-directional push from server to client over HTTP. ROAR should add `TransportType.SSE = "sse"` as a first-class value. This is already the mechanism used by A2A streaming and MCP Streamable HTTP, so making it explicit improves adapter clarity.

### Security Layer

For all production cross-machine transports:
- **Minimum:** HMAC-SHA256 per-message signing (already implemented in `ROARMessage.sign()`)
- **Recommended:** TLS at the transport layer (handled by the operator, not ROAR)
- **High-assurance:** mTLS with agent certificates derived from Layer 1 DIDs
- **Local/dev:** `auth_method = "none"` is acceptable for localhost stdio

---

*Generated: 2026-03-13 | See SDK-ROADMAP.md for implementation status*
