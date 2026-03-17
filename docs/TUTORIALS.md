# ROAR Protocol — Video Tutorial Scripts

> Scripts for the ROAR tutorial video series. Each one stands on its own — record them in any order.

---

## Tutorial Series Overview

| # | Title | Audience | Duration | Prerequisites |
|:-:|:------|:---------|:--------:|:--------------|
| 1 | Getting Started with ROAR | Beginners | ~12 min | Python 3.10+ |
| 2 | Running a ROAR Hub | Intermediate | ~15 min | Tutorial 1 |
| 3 | Using the SDKs | Intermediate | ~18 min | Tutorial 1 |
| 4 | Security Basics | All levels | ~10 min | Tutorial 1 |

---

## Tutorial 1: Getting Started with ROAR

**Goal:** Explain what ROAR is, why it exists, and build a working two-agent system in under 12 minutes.

### Outline

#### Section 1 — What is ROAR? (2 min)

**Talking points:**
- ROAR = Routable Open Agent Runtime
- The problem: MCP, A2A, and ACP each solve one piece — ROAR unifies them
- Show the comparison table (ROAR vs MCP vs A2A vs ACP)
- Analogy: "TCP/IP for AI agents" — identity, routing, signing, streaming in one stack
- Show the 5-layer diagram (use Mermaid from `docs/DIAGRAMS.md`)

**Visual:** Layer stack diagram with brief label for each layer.

#### Section 2 — Install the SDK (1 min)

**Demo:**
```bash
pip install roar-sdk
# or with CLI tools:
pip install 'roar-sdk[cli]'
```

**Talking points:**
- Minimal dependencies (only `pydantic` required)
- Optional extras: `cli`, `websocket`, `grpc`

#### Section 3 — Create Your First Agent Identity (2 min)

**Demo code:**
```python
from roar_sdk import AgentIdentity

agent = AgentIdentity(
    display_name="my-first-agent",
    agent_type="agent",
    capabilities=["greeting", "demo"],
)

print(f"DID: {agent.did}")
print(f"Type: {agent.agent_type}")
print(f"Capabilities: {agent.capabilities}")
```

**Talking points:**
- W3C DID format: `did:roar:<type>:<slug>-<hex>`
- Four agent types: `agent`, `tool`, `human`, `ide`
- Capabilities are advisory — they tell other agents what you can do
- DIDs are self-sovereign — no central authority needed

#### Section 4 — Build and Send a Message (3 min)

**Demo code:**
```python
from roar_sdk import ROARMessage, MessageIntent, AgentIdentity

sender = AgentIdentity(display_name="alice", capabilities=["code"])
receiver = AgentIdentity(display_name="bob", capabilities=["review"])

msg = ROARMessage(
    **{"from": sender, "to": receiver},
    intent=MessageIntent.DELEGATE,
    payload={"task": "review", "files": ["main.py"]},
)

# Sign it
msg.sign(secret="shared-secret")
print(f"Signature: {msg.auth['signature'][:40]}...")

# Verify it
assert msg.verify(secret="shared-secret")
print("Signature verified!")
```

**Talking points:**
- One message format for everything — `ROARMessage`
- 7 intents: execute, delegate, update, ask, respond, notify, discover
- HMAC-SHA256 signing over canonical JSON body
- Replay protection: 5-minute timestamp window + message ID dedup

#### Section 5 — Run a Server and Client (3 min)

**Demo — Terminal 1 (server):**
```python
from roar_sdk import ROARServer, ROARMessage, MessageIntent, AgentIdentity

server_id = AgentIdentity(display_name="echo-server", capabilities=["echo"])
server = ROARServer(server_id, port=8089)

@server.on(MessageIntent.DELEGATE)
async def handle(msg: ROARMessage) -> ROARMessage:
    print(f"Received: {msg.payload}")
    return ROARMessage(
        **{"from": server.identity, "to": msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={"echo": msg.payload},
    )

server.serve()
```

**Demo — Terminal 2 (client):**
```python
from roar_sdk import ROARClient, MessageIntent, AgentIdentity

client_id = AgentIdentity(display_name="my-client")
client = ROARClient(client_id, signing_secret="demo-secret")

response = await client.send_remote(
    to_agent_id="did:roar:agent:echo-server-...",
    intent=MessageIntent.DELEGATE,
    content={"task": "hello"},
)
print(f"Response: {response.payload}")
```

**Talking points:**
- Server listens on a port with intent handlers
- Client discovers and sends signed messages
- Point viewers to `examples/python/echo_server.py` for the full runnable version

#### Section 6 — What's Next? (1 min)

- Tutorial 2: Running a hub for multi-agent orchestration
- Tutorial 3: Using TypeScript, Go, and Rust SDKs
- Tutorial 4: Security deep dive — Ed25519, delegation tokens, key rotation
- Link to full docs and examples

---

## Tutorial 2: Running a ROAR Hub

**Goal:** Set up a ROAR hub, register agents, and show off discovery and federation.

### Outline

#### Section 1 — What is a Hub? (2 min)

**Talking points:**
- A hub is a federation node — it stores agent registrations and enables discovery
- Agents register their AgentCards with the hub
- Other agents query the hub to find collaborators by capability
- Hubs can sync with each other (federation) for cross-machine discovery

**Visual:** Hub interaction diagram from `docs/DIAGRAMS.md` Section 5.

#### Section 2 — Start a Hub with the CLI (2 min)

**Demo:**
```bash
# Start the hub
roar hub start

# In another terminal, check it's running
roar hub agents
# → (empty list)
```

**Talking points:**
- The hub exposes REST endpoints: `/roar/agents`, `/roar/message`, `/roar/ws`
- Default port: 8090
- Uses SQLite for persistent storage (agents survive restarts)

#### Section 3 — Register Agents (3 min)

**Demo code:**
```python
import httpx
from roar_sdk import AgentIdentity, AgentCard

# Create an agent with an AgentCard
identity = AgentIdentity(
    display_name="code-reviewer",
    capabilities=["python", "code-review", "security"],
)
card = AgentCard(
    identity=identity,
    description="Reviews Python code for quality and security issues",
    skills=["code_review", "security_audit"],
    endpoints={"http": "http://localhost:8091"},
)

# Register with the hub via its REST API
async with httpx.AsyncClient() as client:
    resp = await client.post(
        "http://localhost:8090/roar/agents",
        json=card.model_dump(),
    )
    print(resp.json())  # {"registered": True}
```

**Demo (verify via CLI):**
```bash
roar hub agents
# → code-reviewer (python, code-review, security)

roar hub search code-review
# → Found: code-reviewer at http://localhost:8091
```

#### Section 4 — Discovery in Action (3 min)

**Demo — Agent A finds Agent B:**
```python
import httpx

# Query the hub for agents with a specific capability
async with httpx.AsyncClient() as client:
    resp = await client.get(
        "http://localhost:8090/roar/agents",
        params={"capability": "code-review"},
    )
    agents = resp.json()["agents"]
    for agent in agents:
        print(f"{agent['identity']['display_name']}: {agent['description']}")
        print(f"  Endpoint: {agent['endpoints']}")
```

**Or use the local directory for in-process discovery:**
```python
from roar_sdk import AgentDirectory

directory = AgentDirectory()
directory.register(card)
results = directory.search("code-review")
```

**Talking points:**
- Capability-based search — you don't need to know agent names or addresses
- AgentCards include endpoints so you know *how* to reach the agent
- DiscoveryCache provides TTL+LRU caching to minimize hub queries

#### Section 5 — Hub Federation (3 min)

**Demo — Two hubs syncing:**
```bash
# Terminal 1: Hub A on port 8090
roar hub start --port 8090

# Terminal 2: Hub B on port 8095
roar hub start --port 8095

# Register an agent on Hub A
# ... (agent registration code)

# Hub B can pull agents from Hub A
curl -X POST http://localhost:8095/roar/federation/sync \
  -H "Content-Type: application/json" \
  -d '{"hub_url": "http://localhost:8090"}'
```

**Visual:** Federation diagram from `docs/DIAGRAMS.md` Section 6.

**Talking points:**
- Push and pull sync modes
- Agents registered on Hub A become discoverable on Hub B
- No central coordinator — hubs are peers

#### Section 6 — Docker Deployment (2 min)

**Demo:**
```bash
docker compose up
# Hub at :8090, Agent A at :8091, Agent B at :8092
```

**Talking points:**
- Pre-built Docker images for quick deployment
- Docker Compose template includes hub + demo agents
- See `deployment/` for production templates

---

## Tutorial 3: Using the SDKs

**Goal:** Walk through cross-language usage with Python, TypeScript, Go, and Rust. Show that all SDKs produce compatible wire formats.

### Outline

#### Section 1 — SDK Overview (2 min)

**Talking points:**
- 4 SDKs: Python (reference), TypeScript (reference), Go, Rust
- All conform to the same JSON schemas in `spec/schemas/`
- Conformance tests ensure cross-language compatibility
- Same wire format — a Python agent can talk to a TypeScript agent seamlessly

**Visual:** SDK parity table.

| Feature | Python | TypeScript | Go | Rust |
|:--------|:------:|:----------:|:--:|:----:|
| AgentIdentity | Yes | Yes | Yes | Yes |
| ROARMessage | Yes | Yes | Yes | Yes |
| HMAC Signing | Yes | Yes | Yes | Yes |
| Ed25519 | Yes | Yes | Planned | Planned |
| ROARClient | Yes | Yes | Yes | -- |
| ROARServer | Yes | Yes | Yes | Yes |
| Hub | Yes | Yes | Yes | Yes |

#### Section 2 — Python SDK (3 min)

**Demo:** Quick recap from Tutorial 1 — create identity, build message, sign and verify.

```python
from roar_sdk import AgentIdentity, ROARMessage, MessageIntent

agent = AgentIdentity(display_name="py-agent", capabilities=["python"])
msg = ROARMessage(
    **{"from": agent, "to": other_agent},
    intent=MessageIntent.EXECUTE,
    payload={"action": "run_tests"},
)
msg.sign(secret="shared")
print(msg.model_dump_json(indent=2))
```

#### Section 3 — TypeScript SDK (4 min)

**Demo:**
```typescript
import { AgentIdentity, ROARMessage, MessageIntent, sign, verify } from '@roar-protocol/sdk';

const agent: AgentIdentity = {
  did: '', // auto-generated
  display_name: 'ts-agent',
  agent_type: 'agent',
  capabilities: ['typescript', 'frontend'],
  version: '1.0',
};

const msg = new ROARMessage({
  from: agent,
  to: otherAgent,
  intent: MessageIntent.DELEGATE,
  payload: { task: 'build UI component' },
});

const signed = sign(msg, 'shared-secret');
console.log(JSON.stringify(signed, null, 2));

// Verify
const valid = verify(signed, 'shared-secret');
console.log(`Valid: ${valid}`);
```

**Talking points:**
- Same wire format as Python — canonical JSON, same signing algorithm
- TypeScript SDK supports stdio transport for local agent communication
- Browser/WASM build available for web applications

#### Section 4 — Go SDK (3 min)

**Demo:**
```go
package main

import (
    "fmt"
    roar "github.com/ProwlrBot/roar-protocol/go"
)

func main() {
    agent := roar.AgentIdentity{
        DisplayName:  "go-agent",
        AgentType:    "agent",
        Capabilities: []string{"go", "backend"},
        Version:      "1.0",
    }
    agent.GenerateDID()

    msg := roar.ROARMessage{
        From:    agent,
        To:      otherAgent,
        Intent:  roar.IntentExecute,
        Payload: map[string]interface{}{"action": "compile"},
    }

    signature := roar.SignMessage(msg, "shared-secret")
    fmt.Printf("Signature: %s\n", signature)
}
```

**Talking points:**
- Core types, signing, server, hub, and HTTP client all available
- Type-safe with Go structs
- Canonical JSON serialization matches Python/TypeScript

#### Section 5 — Rust SDK (3 min)

**Demo:**
```rust
use roar_sdk::{AgentIdentity, ROARMessage, MessageIntent, sign_message};

let agent = AgentIdentity {
    did: String::new(),
    display_name: Some("rust-agent".into()),
    agent_type: "agent".into(),
    capabilities: vec!["rust".into(), "systems".into()],
    version: "1.0".into(),
    public_key: None,
};

let msg = ROARMessage {
    from: agent.clone(),
    to: other_agent,
    intent: MessageIntent::Execute,
    payload: serde_json::json!({"action": "optimize"}),
    ..Default::default()
};

let signature = sign_message(&msg, "shared-secret");
println!("Signature: {}", signature);
```

**Talking points:**
- Serde-compatible types for easy JSON serialization
- Memory safety from Rust without sacrificing performance
- Core types, signing, server, and hub available

#### Section 6 — Cross-SDK Conformance (3 min)

**Demo:**
```bash
# Run conformance tests from the repo root
cd tests/
python -m pytest test_conformance_signatures.py -v
python -m pytest test_conformance_edge_cases.py -v
```

**Talking points:**
- Golden fixtures in `tests/conformance/golden/`
- Same message, signed by any SDK, verified by any other
- This is how we guarantee protocol interoperability across languages

---

## Tutorial 4: Security Basics

**Goal:** Explain ROAR's security model in practical terms. Cover signing, key types, delegation, and common pitfalls.

### Outline

#### Section 1 — Why Security Matters for Agents (1 min)

**Talking points:**
- Agents act on your behalf — you need to know *who* sent a message
- Without signing, any process can impersonate any agent
- Without replay protection, intercepted messages can be re-sent
- ROAR makes security the default: every message is signed and verified

#### Section 2 — HMAC-SHA256 Signing (3 min)

**Demo:**
```python
from roar_sdk import ROARMessage, MessageIntent, AgentIdentity

msg = ROARMessage(
    **{"from": sender, "to": receiver},
    intent=MessageIntent.EXECUTE,
    payload={"action": "delete_file", "path": "/important.txt"},
)

# Sign with shared secret
msg.sign(secret="my-shared-secret")
print(f"Signature: {msg.auth['signature']}")
print(f"Timestamp: {msg.auth['timestamp']}")

# Verification
assert msg.verify(secret="my-shared-secret")  # True
assert not msg.verify(secret="wrong-secret")   # False

# Tamper with payload — signature breaks
msg.payload["path"] = "/etc/passwd"
assert not msg.verify(secret="my-shared-secret")  # False!
```

**Talking points:**
- Canonical JSON body: all fields sorted alphabetically, deterministic
- Covers: id, from.did, to.did, intent, payload, context, timestamp
- `sort_keys=True` ensures cross-language consistency
- Shared secret = both sides know the key (same-machine, same-org)

**Visual:** Signing flow diagram from `docs/DIAGRAMS.md` Section 3.

#### Section 3 — Ed25519 for Cross-Organization Trust (2 min)

**Talking points:**
- When you can't share a secret (different organizations), use public-key crypto
- Agent signs with private key, receiver verifies with public key
- Public key comes from the agent's DID Document or trusted directory
- **Security rule:** NEVER trust a key supplied only in the message body
- Ed25519 = fast, small keys (32 bytes), small signatures (64 bytes)

**Demo:**
```python
from roar_sdk.signing import sign_ed25519, verify_ed25519

# Agent with Ed25519 key
agent = AgentIdentity(
    display_name="secure-agent",
    public_key="a1b2c3d4..."  # Ed25519 hex-encoded
)

# Sign with Ed25519 (standalone function, not a message method)
signature = sign_ed25519(message_bytes, private_key_bytes)

# Receiver verifies using public key from a trusted source
# (DID Document, hub registry — NEVER from the message itself)
valid = verify_ed25519(message_bytes, signature, public_key_bytes)
```

#### Section 4 — Replay Protection (1 min)

**Talking points:**
- Every message has a timestamp baked into the signing body
- Receivers reject messages older than 5 minutes (configurable)
- Receivers reject future timestamps beyond 30 seconds skew
- Message ID dedup cache prevents replaying the exact same message
- Both checks MUST pass — this is "fail closed" security

#### Section 5 — Delegation Tokens (2 min)

**Demo:**
```python
import time
from roar_sdk.delegation import DelegationToken, issue_token

# Create a delegation token — Alice grants Bob "code-review" capability
token = DelegationToken(
    delegator_did=alice.did,
    delegate_did=bob.did,
    capabilities=["code-review"],
    expires_at=time.time() + 3600,  # 1 hour from now
)

# Sign the token (in practice, use issue_token() which handles this)
# The signed token travels with the DELEGATE message in the context field
```

**Talking points:**
- Scoped: only grants specific capabilities
- Time-limited: always has an expiration (`expires_at` is a Unix timestamp)
- Cryptographically signed: can be verified offline
- Travels with messages: no need to call back to the issuer

**Visual:** Delegation token flow from `docs/DIAGRAMS.md` Section 7.

#### Section 6 — Security Checklist (1 min)

Quick summary for developers:

1. **Always sign messages** in production — never use `auth_method: none` outside localhost
2. **Use Ed25519** for cross-organization communication
3. **Rotate shared secrets** regularly — support key overlap during rotation
4. **Deploy DNSSEC** if using DNS-based discovery
5. **Monitor auth failures** — they may indicate attack attempts
6. **Check delegation token expiry** before acting on delegated tasks
7. **Never trust keys from message bodies** — always resolve from DID Documents or trusted directories

---

## Recording Notes

### Technical Setup
- Use a dark terminal theme for contrast
- Split screen: code editor on left, terminal on right
- Pre-install all dependencies to avoid waiting during recording
- Have the hub and agents pre-configured but show the setup steps

### Style Guidelines
- Keep a natural pace — these are technical, not marketing videos
- Show real output from real commands, don't fake it
- When showing code, type it out (or use a slow reveal) rather than pasting big blocks
- Include the terminal prompt so viewers know which machine/terminal you're on
- Add chapter markers for YouTube navigation

### Assets Needed
- ROAR logo/branding for intro/outro
- Mermaid diagrams rendered as images (export from `docs/DIAGRAMS.md`)
- Terminal recordings (asciinema or similar)
- Code snippets pre-tested against current SDK versions

---

<p align="center">
  <sub>Tutorial scripts for ROAR Protocol v0.3.0</sub><br/>
  <sub>See <a href="../examples/">examples/</a> for runnable code referenced in these tutorials.</sub>
</p>
