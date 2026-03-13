# roar-sdk

**ROAR Protocol** — Python SDK. 5-layer agent communication standard.

[![PyPI](https://img.shields.io/pypi/v/roar-sdk)](https://pypi.org/project/roar-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/roar-sdk)](https://pypi.org/project/roar-sdk/)
[![License](https://img.shields.io/pypi/l/roar-sdk)](https://github.com/ProwlrBot/roar-protocol/blob/main/python/pyproject.toml)

Design by [@kdairatchi](https://github.com/kdairatchi) — [ProwlrBot/roar-protocol](https://github.com/ProwlrBot/roar-protocol)

---

## Install

```bash
pip install roar-sdk                    # core: types, client, server (pydantic only)
pip install 'roar-sdk[http]'            # + httpx for HTTP transport
pip install 'roar-sdk[websocket]'       # + websockets transport
pip install 'roar-sdk[ed25519]'         # + Ed25519 signing (cryptography)
pip install 'roar-sdk[server]'          # + fastapi + uvicorn for serving
pip install 'roar-sdk[server,ed25519]'  # full stack
```

---

## Quick Start

```python
from roar_sdk import AgentIdentity, ROARMessage, MessageIntent, ROARClient, ROARServer

# Layer 1: identity
agent = AgentIdentity(display_name="my-agent", capabilities=["code"])

# Layer 4: build and sign a message
msg = ROARMessage(
    **{"from": agent, "to": other},
    intent=MessageIntent.DELEGATE,
    payload={"task": "review"},
)
msg.sign("shared-secret")

# Layer 3: send over HTTP
client = ROARClient(agent, signing_secret="shared-secret")
response = await client.send_remote(
    to_agent_id=other.did,
    intent=MessageIntent.DELEGATE,
    content={"task": "review"},
)
```

---

## What's in the Box

| Module | What it gives you |
|:-------|:-----------------|
| `AgentIdentity`, `AgentCard` | Layer 1 — W3C DID-based agent identity |
| `AgentDirectory`, `SQLiteAgentDirectory` | Layer 2 — in-memory and persistent discovery |
| `ROARHub` | Layer 2 — federated hub with REST API |
| `DiscoveryCache` | Layer 2 — TTL+LRU discovery cache |
| `ROARClient`, `ROARServer` | Layer 3 — HTTP client and server |
| `create_roar_router` | Layer 3 — FastAPI router (HTTP + WebSocket + SSE) |
| `ROARMessage`, `MessageIntent` | Layer 4 — unified message format |
| `sign_ed25519`, `verify_ed25519` | Layer 4 — asymmetric signing |
| `DelegationToken`, `issue_token` | Layer 4 — scoped capability grants |
| `EventBus`, `StreamFilter` | Layer 5 — real-time event streaming |
| `IdempotencyGuard` | Layer 5 — deduplication |
| `DIDDocument`, `DIDKeyMethod`, `DIDWebMethod` | Identity — W3C DID documents |
| `AutonomyLevel`, `CapabilityDelegation` | Identity — graduated autonomy model |
| `MCPAdapter`, `A2AAdapter`, `ACPAdapter` | Adapters — MCP, A2A, ACP bridges |
| `detect_protocol` | Adapters — auto-detect incoming protocol |

---

## Server Example

```python
from fastapi import FastAPI
from roar_sdk import AgentIdentity, MessageIntent, ROARMessage, ROARServer
from roar_sdk.router import create_roar_router

identity = AgentIdentity(display_name="code-reviewer", capabilities=["code-review"])
server = ROARServer(identity, signing_secret="shared-secret")

@server.on(MessageIntent.DELEGATE)
async def handle_delegate(msg: ROARMessage) -> ROARMessage:
    return ROARMessage(
        **{"from": server.identity, "to": msg.from_identity},
        intent=MessageIntent.RESPOND,
        payload={"review": "LGTM"},
        context={"in_reply_to": msg.id},
    )

app = FastAPI()
app.include_router(create_roar_router(server, rate_limit=60))
# uvicorn main:app --port 8089
```

---

## Protocol Adapters

```python
from roar_sdk import MCPAdapter, A2AAdapter, ACPAdapter
from roar_sdk.adapters.detect import detect_protocol, ProtocolType

# Auto-detect incoming format
protocol = detect_protocol(raw_json)

if protocol == ProtocolType.MCP:
    msg = MCPAdapter.mcp_to_roar(tool_name, params, agent)
elif protocol == ProtocolType.A2A:
    msg = A2AAdapter.a2a_task_to_roar(task, sender, receiver)
elif protocol == ProtocolType.ACP:
    msg = ACPAdapter.acp_message_to_roar(acp_msg, ide, agent)
```

---

## Links

- [PyPI](https://pypi.org/project/roar-sdk/)
- [Specification](https://github.com/ProwlrBot/roar-protocol/blob/main/ROAR-SPEC.md)
- [Architecture](https://github.com/ProwlrBot/roar-protocol/blob/main/ARCHITECTURE.md)
- [Examples](https://github.com/ProwlrBot/roar-protocol/tree/main/examples/python)
- [Conformance tests](https://github.com/ProwlrBot/roar-protocol/tree/main/tests/conformance)
