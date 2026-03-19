<p align="center">
  <img src="https://img.shields.io/badge/by-kdairatchi-00E5FF?style=for-the-badge&logoColor=white" alt="by kdairatchi" />
  &nbsp;
  <img src="https://img.shields.io/badge/ProwlrBot-ROAR%20Protocol-00E5FF?style=for-the-badge&logoColor=white" alt="ROAR Protocol" />
</p>

<h1 align="center">ROAR Protocol</h1>

<p align="center">
  <strong>How agents talk to each other.</strong><br/>
  <sub>A 5-layer communication standard for autonomous AI agents. Designed by <a href="https://github.com/kdairatchi">kdairatchi</a>.</sub>
</p>

<p align="center">
  <a href="https://github.com/ProwlrBot/prowlrbot"><img src="https://img.shields.io/badge/reference%20impl-prowlrbot-00E5FF?style=flat-square" /></a>
  <a href="https://github.com/ProwlrBot/roar-protocol/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" /></a>
  <img src="https://img.shields.io/badge/spec-v0.3.0-orange?style=flat-square" />
  <img src="https://img.shields.io/badge/status-active-green?style=flat-square" />
</p>

---

> *"The single biggest problem in communication is the illusion that it has taken place."*
> — George Bernard Shaw

---

## What Is ROAR?

**R**outable **O**pen **A**gent **R**untime.

I built ROAR because I kept hitting the same wall: MCP handles tools well, A2A handles agent delegation well, ACP handles IDE integration well — but none of them talk to each other, and none of them know *who* an agent is. Every multi-agent system I built required the same glue code: identity, routing, signing, streaming.

ROAR is what I wish existed when I started building [ProwlrBot](https://github.com/ProwlrBot/prowlrbot). It's a 5-layer stack that gives agents a real identity (W3C DIDs), lets them find each other (federated discovery), and exchanges messages in one unified format that works over stdio, HTTP, WebSocket, or gRPC — with signing, streaming, and backward bridges to MCP and A2A built in.

Think TCP/IP, but for AI agents.

---

## Scope

**This repo contains the protocol specification and the reference SDKs.** It defines:

- The canonical type definitions (wire format, field names, enums)
- JSON Schemas — the contract that all SDK implementations must conform to
- Conformance tests — language-agnostic golden fixtures
- The Python reference SDK (`python/`)
- The TypeScript reference SDK (`ts/`)

**What this repo is not:**

- A production-ready platform (see [SDK-ROADMAP.md](SDK-ROADMAP.md) for stability status)
- A replacement for MCP, A2A, or ACP — ROAR bridges all three

---

## Where's the Code?

| SDK | Status | Location |
|:----|:-------|:---------|
| **Python** | Reference implementation — `roar-sdk` on PyPI | [`python/`](python/) |
| **TypeScript** | Reference implementation — `@roar-protocol/sdk` on npm | [`ts/`](ts/) |
| **Go** | Types, signing, client, server, hub | [`go/`](go/) |
| **Rust** | Types, signing, server, hub (serde + tiny_http) | [`rust/`](rust/) |
| **Browser/WASM** | Web Crypto API, browser-native | [`ts/browser/`](ts/browser/) |

See [SDK-ROADMAP.md](SDK-ROADMAP.md) for open tasks, divergence issues, and what needs work.

---

## The 5 Layers

```
┌────────────────────────────────────────────────────────┐
│  Layer 5: Stream    Real-time events (11 types, SSE/WS)│
├────────────────────────────────────────────────────────┤
│  Layer 4: Exchange  One message format, 7 intents      │
├────────────────────────────────────────────────────────┤
│  Layer 3: Connect   Transport negotiation              │
├────────────────────────────────────────────────────────┤
│  Layer 2: Discovery Capability search, federated dirs  │
├────────────────────────────────────────────────────────┤
│  Layer 1: Identity  W3C DID-based, no central auth     │
└────────────────────────────────────────────────────────┘
```

Layers are independently adoptable. You can use Identity + Discovery without the full stack.

---

## Implement ROAR in 5 Steps

**Step 1 — Give your agent an identity**

```python
from roar_sdk import AgentIdentity

agent = AgentIdentity(
    display_name="my-agent",
    agent_type="agent",
    capabilities=["code", "review"],
)
print(agent.did)  # did:roar:agent:my-agent-a1b2c3d4
```

**Step 2 — Publish an Agent Card so others can find you**

```python
from roar_sdk import AgentCard, AgentDirectory

card = AgentCard(
    identity=agent,
    description="Reviews Python code for quality and security",
    endpoints={"http": "http://localhost:8089"},
)
directory = AgentDirectory()
directory.register(card)
```

**Step 3 — Choose an intent and build a message**

```python
from roar_sdk import ROARMessage, MessageIntent

msg = ROARMessage(
    **{"from": sender_identity, "to": receiver_identity},
    intent=MessageIntent.DELEGATE,
    payload={"task": "review", "files": ["main.py"]},
)
```

**Step 4 — Sign and send**

```python
msg.sign(secret="shared-secret")
# msg.auth → {"signature": "hmac-sha256:...", "timestamp": 1710000000.0}

# Send over HTTP
from roar_sdk import ROARClient
client = ROARClient(sender_identity, signing_secret="shared-secret")
response = await client.send_remote(
    to_agent_id=receiver_identity.did,
    intent=MessageIntent.DELEGATE,
    content={"task": "review", "files": ["main.py"]},
)
```

**Step 5 — Handle messages on the server**

```python
from roar_sdk import ROARServer

server = ROARServer(receiver_identity, port=8089)

@server.on(MessageIntent.DELEGATE)
async def handle_delegate(msg: ROARMessage) -> ROARMessage:
    return ROARMessage(
        **{"from": server.identity, "to": msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={"status": "ok", "review": "LGTM"},
    )
```

See [examples/python/](examples/python/) for runnable versions.

---

## Why ROAR?

The existing protocols each solve one slice of the problem:

| Feature | ROAR | MCP | A2A | ACP |
|:--------|:----:|:---:|:---:|:---:|
| Agent identity (W3C DID) | ✅ | ❌ | ❌ | ❌ |
| Federated discovery | ✅ | ❌ | Agent Cards only | ❌ |
| Tool invocation | ✅ | ✅ | ❌ | Partial |
| Agent-to-agent delegation | ✅ | ❌ | ✅ | ❌ |
| IDE integration | ✅ | ❌ | ❌ | ✅ |
| Message signing | ✅ | ❌ | ❌ | ❌ |
| Real-time streaming | ✅ | SSE only | SSE only | ❌ |
| Transports | 4 | 2 | 1 | 2 |
| Graduated autonomy | ✅ | ❌ | ❌ | ❌ |

**ROAR does not replace MCP or A2A.** It provides a unified identity and message envelope so you can use MCP, A2A, and ACP together in the same system. The MCPAdapter and A2AAdapter translate automatically.

### Concrete Scenario

An IDE (Claude Code) delegates work to a local ROAR agent, which in turn delegates to a cloud agent that uses MCP tools. Without ROAR, each handoff requires a custom integration. With ROAR:

```
IDE (did:roar:ide:claude-...)
  → DELEGATE → Router Agent (did:roar:agent:router-...)
    → DELEGATE → Cloud Agent (did:roar:agent:cloud-...)
      → EXECUTE → MCP Tool (did:roar:tool:shell-...)
        → RESPOND ←
      ← RESPOND ←
    ← RESPOND ←
  ← RESPOND ←
```

Every hop uses the same `ROARMessage` format. Every agent is identified by DID. Every message is signed and replay-protected.

### Security Model

Two signing algorithms serve different needs:

| Scenario | Algorithm | Where |
|:---------|:----------|:------|
| Same-machine, shared secret | HMAC-SHA256 | Default for all messages |
| Cross-machine, no shared secret | Ed25519 | `public_key` in AgentIdentity |

End-to-end flow:

1. Agent A constructs message, signs with HMAC: `msg.sign(secret)`
2. Agent B receives, verifies: `msg.verify(secret)` — includes timestamp check (5min window)
3. Agent B responds, signs own reply
4. Agent A verifies the response

See [spec/04-exchange.md](spec/04-exchange.md) for the canonical signing body definition.

---

## The 7 Intents

All communication uses one of seven intents. No more custom action types.

| Intent | Direction | Use case |
|:-------|:----------|:---------|
| `execute` | Agent → Tool | Run a tool or shell command |
| `delegate` | Agent → Agent | Hand off a task to another agent |
| `update` | Agent → IDE | Report progress or intermediate results |
| `ask` | Agent → Human | Request input or approval |
| `respond` | Any → Any | Reply to execute/delegate/ask |
| `notify` | Any → Any | One-way notification, no reply expected |
| `discover` | Any → Directory | Find agents by capability |

---

## The Spec

| Document | Contents |
|:---------|:---------|
| [ROAR-SPEC.md](ROAR-SPEC.md) | Full overview — read this first |
| [spec/01-identity.md](spec/01-identity.md) | Layer 1: DID format, AgentCard, Ed25519 |
| [spec/02-discovery.md](spec/02-discovery.md) | Layer 2: Directory, search, federation |
| [spec/03-connect.md](spec/03-connect.md) | Layer 3: Transports, sessions, reconnection |
| [spec/04-exchange.md](spec/04-exchange.md) | Layer 4: ROARMessage, intents, signing |
| [spec/05-stream.md](spec/05-stream.md) | Layer 5: StreamEvents, backpressure, SSE |
| [spec/schemas/](spec/schemas/) | JSON Schemas — canonical contracts for all SDKs |
| [spec/VERSION.json](spec/VERSION.json) | Current spec + SDK compatibility versions |
| [docs/DIAGRAMS.md](docs/DIAGRAMS.md) | Mermaid diagrams — architecture, message flow, delegation, discovery |

---

## Conformance Tests

Language-agnostic golden fixtures that any compliant SDK must pass:

```
tests/conformance/golden/
├── identity.json       # Valid AgentIdentity — parse, round-trip, DID format
├── message.json        # Valid ROARMessage — field names, intent enum values
├── stream-event.json   # Valid StreamEvent — type enum, source DID
└── signature.json      # HMAC canonical body + expected signature
```

See [tests/README.md](tests/README.md) for how to run conformance tests against your implementation.

---

## Quick Start — Docker

```bash
docker compose up        # Hub + 2 demo agents
```

Hub at `http://localhost:8090`, Agent A at `:8091`, Agent B at `:8092`.

## Quick Start — CLI

```bash
pip install -e './python[cli]'
roar hub start                       # Start a hub
roar hub agents                      # List registered agents
roar hub search code-review          # Find agents by capability
roar send http://localhost:8091 did:roar:agent:test '{"task":"review"}'
```

## Examples

| Example | What it shows |
|:--------|:-------------|
| [examples/demo/](examples/demo/) | **3-terminal demo** — Hub + Agent A + Agent B with Ed25519 registration and discovery |
| [examples/python/echo_server.py](examples/python/echo_server.py) | Minimal ROARServer echoing DELEGATE messages |
| [examples/python/client.py](examples/python/client.py) | ROARClient discovering the server and sending a message |
| [examples/python/demo_hub_two_agents.py](examples/python/demo_hub_two_agents.py) | Single-script visual demo of the full protocol |
| [examples/quickstart/](examples/quickstart/) | Step-by-step quickstart guides (Python + TypeScript) |
| [examples/demo/cross_framework.py](examples/demo/cross_framework.py) | Cross-framework bridging (AutoGen, CrewAI, LangGraph) |

---

## The Ecosystem

| Repo | Role |
|:-----|:-----|
| [prowlrbot](https://github.com/ProwlrBot/prowlrbot) | Platform + reference implementation |
| [prowlr-marketplace](https://github.com/ProwlrBot/prowlr-marketplace) | Community registry |
| **roar-protocol** (you are here) | Protocol specification |
| [prowlr-docs](https://github.com/ProwlrBot/prowlr-docs) | Full documentation |
| [agentverse](https://github.com/ProwlrBot/agentverse) | Virtual world using ROAR StreamEvents |

---

## Contributing

Found a gap in the spec? Want to propose a change?

1. Open an issue using the [Spec Change template](.github/ISSUE_TEMPLATE/spec_change.md)
2. Label it `proposal`
3. Discuss — once accepted, PR with updated spec + schema + `VERSION.json` bump
4. Link reference SDK PRs so changes can be verified end-to-end

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

---

## Origin

I'm [@kdairatchi](https://github.com/kdairatchi). I started building an autonomous agent platform and kept running into the same friction: agents that couldn't find each other, messages without a standard format, and protocol integrations that were one-offs every time.

ROAR came out of building real multi-agent systems and getting frustrated with the gaps. The design emerged from studying MCP, A2A, ACP, W3C DIDs, and DIDComm — then distilling what was genuinely missing: a single identity layer, a single message envelope, and real federation between them.

The name felt right. Agents should be heard. The protocol should be invisible.

---

<p align="center">
  <sub>Protocols are invisible when they work. That is the goal.</sub><br/>
  <sub>Found a spec gap? <a href="https://github.com/ProwlrBot/roar-protocol/issues">Open an issue.</a></sub>
</p>
