# Phase 1: Competitive Landscape Analysis

**Project ROAR — Research Plan, Phase 1**
Version: 1.0 | Status: Draft

---

## Overview

The agentic AI ecosystem has produced four major interoperability protocols in parallel, each addressing a narrow slice of the agent communication problem. ROAR (Routable Open Agent Runtime) is designed as a unified 5-layer stack that subsumes all of them without replacing them — any existing MCP, A2A, ACP, or ANP agent can participate in a ROAR network through adapters.

This document maps each protocol's architecture, identifies its gaps, and defines the use cases that ROAR uniquely enables.

---

## Protocol Analysis

### 1. MCP — Model Context Protocol (Anthropic)

**Purpose:** Standardize how AI models invoke external tools and access context (files, databases, APIs) during inference.

**Architecture:**
- Client-server: the model (MCP client) calls tools exposed by MCP servers
- Transport: HTTP Streamable (POST + SSE) or stdio (subprocess)
- Auth: none defined at protocol level — implementations use OAuth, API keys at the app layer
- Identity: none — servers are identified by URL or process path only
- Discovery: none — servers must be manually configured
- Streaming: SSE for token-by-token results

**Strengths:**
- Widely adopted (Claude, Cursor, Zed, dozens of tools)
- Simple mental model: tools are functions, context is data
- Ecosystem momentum: hundreds of community MCP servers

**Gaps:**
- No agent identity — a server cannot verify *who* is calling it
- No agent-to-agent communication — MCP is tool-use, not agent delegation
- No discovery — agents cannot find each other dynamically
- No signing/authentication at the message level
- No support for delegating subtasks between autonomous agents

**ROAR mapping:** MCP maps entirely to ROAR Layer 4 (`EXECUTE` intent). The `MCPAdapter` in the Python SDK translates MCP tool calls to `ROARMessage(intent=EXECUTE)` and back. Any MCP server can be wrapped as a ROAR agent with Layer 1 identity added.

---

### 2. A2A — Agent-to-Agent Protocol (Google DeepMind)

**Purpose:** Standardize task delegation between enterprise AI agents with human-readable capability discovery.

**Architecture:**
- Agent Cards: JSON manifests published at `/.well-known/agent.json` describing capabilities
- Tasks: stateful units of work with lifecycle (submitted → working → completed/failed)
- Transport: HTTP/REST or SSE for streaming updates
- Auth: none at protocol level — relies on app-layer auth (API keys, OAuth)
- Identity: URL-based — agents are their endpoint, not cryptographically identified
- Discovery: manual card exchange or directory lookup

**Strengths:**
- Practical enterprise focus: task lifecycle, human-in-the-loop interrupts
- Agent Cards give a standard capability advertisement format
- Google backing gives ecosystem credibility

**Gaps:**
- No cryptographic identity — agent URL ≠ verified agent; no trust chain
- HTTP-only — no WebSocket, stdio, or gRPC support
- No federation — no standard way for directories to sync across organizations
- No streaming events beyond SSE task updates
- Agent Cards cannot be signed or attested

**ROAR mapping:** A2A maps to ROAR Layers 2 + 4. Agent Cards become `AgentCard` + `AgentIdentity` in Layer 1 (with DID added). A2A tasks become `ROARMessage(intent=DELEGATE)`. The `A2AAdapter` translates between formats.

---

### 3. ACP — Agent Communication Protocol (IBM / BeeAI)

**Purpose:** Standardize the interface between IDEs/orchestrators and AI agent runtimes for session-based interactions.

**Architecture:**
- Sessions: a human or orchestrator opens a session with an agent, sends messages, receives responses
- HTTP REST with optional SSE for streaming
- Focuses on the IDE-to-agent boundary (e.g. VS Code → local agent)
- No identity layer — agents are identified by local process or URL
- No discovery — agent location is preconfigured

**Strengths:**
- Clean session abstraction that maps well to chat-style interactions
- Good fit for IDE integrations (the Cursor/VS Code use case)
- Simple enough to implement in an afternoon

**Gaps:**
- No agent identity or authentication
- No agent-to-agent communication — designed for human→agent only
- No federation, no cross-organization discovery
- Narrowest scope of the four protocols

**ROAR mapping:** ACP maps to ROAR Layer 3 (Connect/session lifecycle) + Layer 4 (`UPDATE` and `ASK` intents for progress reporting and human approval). A ROAR agent exposing `POST /roar/message` already satisfies ACP clients.

---

### 4. ANP — Agent Network Protocol (Agent Network Protocol Foundation)

**Purpose:** Define a decentralized identity and discovery layer for agents using W3C DIDs and verifiable credentials.

**Architecture:**
- DID-based agent identity (W3C standard)
- P2P discovery using DHT (similar to IPFS/libp2p)
- Capability advertisements using verifiable credentials
- No defined message format — only identity + discovery
- No transport specification — leaves that to implementers
- Status: specification only, limited implementation

**Strengths:**
- Strongest identity model of the four — W3C DID is the right foundation
- Decentralized by design — no central registry required
- Verifiable credentials enable capability attestation without a trusted third party

**Gaps:**
- No message format — you know who an agent is but not how to talk to it
- No transport — no standard for HTTP, WebSocket, or stdio
- No streaming — no pub/sub or event model
- Community and tooling are nascent
- Not production-ready

**ROAR mapping:** ANP maps directly to ROAR Layer 1 (Identity) + Layer 2 (Discovery). ROAR adopts the DID approach from ANP and adds the missing Layers 3-5 on top, making ANP agents immediately usable in a ROAR network.

---

## Gap Analysis Summary

| Use Case | MCP | A2A | ACP | ANP | ROAR |
|---|:---:|:---:|:---:|:---:|:---:|
| Tool invocation (model → function) | ✅ | ⚠️ | ✅ | ❌ | ✅ |
| Agent delegation (agent → agent task) | ❌ | ✅ | ❌ | ❌ | ✅ |
| Cryptographic agent identity | ❌ | ❌ | ❌ | ✅ | ✅ |
| Dynamic capability discovery | ❌ | ⚠️ | ❌ | ✅ | ✅ |
| Cross-org agent federation | ❌ | ❌ | ❌ | ⚠️ | ✅ |
| Real-time streaming events | ⚠️ | ⚠️ | ❌ | ❌ | ✅ |
| Transport flexibility (WS, stdio, gRPC) | ⚠️ | ❌ | ❌ | ❌ | ✅ |
| HMAC-signed messages | ❌ | ❌ | ❌ | ⚠️ | ✅ |
| Human-in-the-loop approval | ❌ | ✅ | ✅ | ❌ | ✅ |
| Backward compat with MCP/A2A | — | — | — | — | ✅ |

✅ = native support | ⚠️ = partial/optional | ❌ = not in scope

---

## Use Cases Impossible Without ROAR

### 1. Multi-agent swarms with verified identity
A fleet of 10 scan agents must coordinate without trusting each other blindly. Today, no protocol provides signed, DID-anchored messages — any agent can impersonate any other. ROAR Layer 1 + 4 solves this with HMAC-SHA256 per-message signing against a shared secret (or Ed25519 per-key signing when that lands).

### 2. Cross-protocol delegation
A Claude Code agent (MCP-native) needs to delegate a subtask to a Google agent (A2A-native). Today these are incompatible wire formats with no translation layer. ROAR provides the `MCPAdapter` and `A2AAdapter` so both can speak to a ROAR hub that routes between them.

### 3. Federated cross-organization discovery
An enterprise wants its internal agents to discover partner-organization agents without a shared directory. Today, every registry is a silo. ROAR Layer 2 defines hub federation (`hub_url` on `DiscoveryEntry`) so hubs can sync capabilities without centralizing identity.

---

## Conclusion

ROAR is not a replacement for MCP, A2A, ACP, or ANP — it is the integration layer that makes them interoperable. Each existing protocol maps to one or two ROAR layers. ROAR fills the identity, signing, federation, and multi-transport gaps that all four protocols leave open.

The community is converging: the Agentic AI Foundation (AAIF, 2024), W3C AI Agent Protocol Community Group, and IETF BANDAID draft all signal that the industry recognizes fragmentation as the core problem. ROAR is positioned to be the synthesis rather than the fifth silo.

---

*Generated: 2026-03-13 | See SDK-ROADMAP.md for implementation status*
