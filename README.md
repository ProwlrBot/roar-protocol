<p align="center">
  <img src="https://img.shields.io/badge/ProwlrBot-ROAR%20Protocol-00E5FF?style=for-the-badge&logoColor=white" alt="ROAR Protocol" />
</p>

<h1 align="center">roar-protocol</h1>

<p align="center">
  <strong>How agents talk to each other.</strong><br/>
  <sub>5-layer communication protocol for autonomous AI agents.</sub>
</p>

<p align="center">
  <a href="https://github.com/ProwlrBot/prowlrbot"><img src="https://img.shields.io/badge/core-prowlrbot-00E5FF?style=flat-square" /></a>
  <a href="https://github.com/ProwlrBot/roar-protocol/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square" /></a>
  <img src="https://img.shields.io/badge/spec-v0.1.0-orange?style=flat-square" />
</p>

---

> *"The single biggest problem in communication is the illusion that it has taken place."* — George Bernard Shaw

---

## What Is ROAR?

**R**outable **O**pen **A**gent **R**untime. A 5-layer protocol stack for agent-to-agent communication. Think TCP/IP, but for AI agents.

## The 5 Layers

```
Layer 5: Stream      Real-time event streaming (8 event types)
Layer 4: Exchange    Unified message format (ROARMessage)
Layer 3: Connect     Transport negotiation (stdio/HTTP/WS/gRPC)
Layer 2: Discovery   Agent directory + capability search
Layer 1: Identity    W3C DID-based agent identity
```

### Layer 1: Identity
W3C DID-based identity with AgentCard. No central authority.

### Layer 2: Discovery
Capability-based search. Federated across networks.

### Layer 3: Connect
Transport-agnostic sessions. stdio, HTTP, WebSocket, or gRPC.

### Layer 4: Exchange
7 intent types: request, response, notify, subscribe, unsubscribe, error, cancel. Signed.

### Layer 5: Stream
Real-time events with backpressure. 8 event types for granular coordination.

## Why ROAR?

| | ROAR | MCP | A2A |
|:--|:----:|:---:|:---:|
| Agent identity | W3C DID | None | Google-specific |
| Discovery | Federated | Manual config | Centralized |
| Transport options | 4 | 2 | 1 |
| Message signing | Built-in | None | None |
| Streaming | 8 event types | Basic | None |

ROAR complements MCP and A2A. ProwlrBot speaks all three.

## Spec Documents

| Document | Contents |
|:---------|:---------|
| ROAR-SPEC.md | Full specification overview |
| ROAR-IDENTITY.md | Layer 1: AgentCard, DID format, keys |
| ROAR-DISCOVERY.md | Layer 2: Directory, search, federation |
| ROAR-CONNECT.md | Layer 3: Transport, sessions, reconnection |
| ROAR-EXCHANGE.md | Layer 4: Messages, intents, signing |
| ROAR-STREAM.md | Layer 5: Events, backpressure, subscriptions |

## The Ecosystem

| Repo | Role |
|:-----|:-----|
| [prowlrbot](https://github.com/ProwlrBot/prowlrbot) | Core platform |
| [prowlr-marketplace](https://github.com/ProwlrBot/prowlr-marketplace) | Community registry |
| **roar-protocol** (you are here) | Protocol spec |
| [prowlr-docs](https://github.com/ProwlrBot/prowlr-docs) | Documentation |
| [agentverse](https://github.com/ProwlrBot/agentverse) | Virtual world |

---

<p align="center">
  <sub>Protocols are invisible when they work. That is the goal.</sub><br/>
  <sub>Found a spec gap? <a href="https://github.com/ProwlrBot/roar-protocol/issues">Open an issue</a>.</sub>
</p>
