# ROAR Universal Protocol Bridge — Design Spec

**Date**: 2026-03-17
**Author**: @kdairatchi + Claude
**Status**: Approved
**Covers**: Spec 009 (Framework Adapters), Spec 002 (DNS Discovery)

## Vision

ROAR becomes the TCP/IP of agent protocols — the universal bridge layer that any protocol (MCP, A2A, ACP) and any framework (CrewAI, LangGraph, AutoGen) routes through to reach agents on other protocols/frameworks.

**Principle**: Transparent ingress (accept any protocol), protocol-aware egress (deliver in the target's preferred format).

## Components

### 1. BridgeRouter (`bridge.py`)
- Wraps the hub with protocol translation
- Incoming: `detect_protocol()` → `normalize_to_roar()` → ROARMessage
- Outgoing: lookup target's `preferred_protocol` → `translate_from_roar()` → deliver
- New endpoint: `POST /roar/bridge` accepts ANY protocol message
- Agents register with `preferred_protocol` field in their card

### 2. MCP Adapter (`adapters/mcp.py`)
- `MCPAdapter.mcp_to_roar()`: `tools/call` → DELEGATE, `tools/list` → DISCOVER
- `MCPAdapter.roar_to_mcp()`: RESPOND → tool result, agent cards → tool list
- Handles JSON-RPC 2.0 envelope (id, method, params, result)

### 3. A2A Adapter (`adapters/a2a.py`)
- `A2AAdapter.a2a_to_roar()`: `tasks/send` → DELEGATE, `tasks/get` → ASK
- `A2AAdapter.roar_to_a2a()`: RESPOND → task artifact, NOTIFY → status update
- Handles A2A task lifecycle (submitted → working → completed)

### 4. DNS Discovery (`dns_discovery.py`)
- **Publish**: Generate DNS-AID SVCB records + `did:web` DID Document + ANP JSON-LD
- **Resolve**: Query `_agents.example.com` → get hub URL → query hub API
- Zone file generator for deployment
- Three discovery paths: DNS-AID, ANP, did:web

### 5. Hub Protocol Endpoint
- `POST /roar/bridge` — accepts any protocol, auto-detects, bridges
- Existing `/roar/message` stays ROAR-native
- AgentCard gains `preferred_protocol` field

## Data Flows

### Demo 1: MCP tool → ROAR → A2A agent
MCP client calls `tools/call("code-review")` → ROAR hub detects MCP, translates to DELEGATE, finds agent with "code-review" capability that prefers A2A, translates to `tasks/send`, delivers, gets task artifact back, returns as MCP tool result.

### Demo 2: Cross-framework (CrewAI ↔ LangGraph)
CrewAI researcher (A2A) delegates to LangGraph analyst (ROAR native). Hub translates both directions. Neither framework knows the other exists.

### Demo 3: DNS discovery → bridge → response
Agent B queries DNS for `_agents.example.com` SVCB → gets hub URL → queries hub for "code-review" → sends A2A `tasks/send` → hub bridges to ROAR agent → response comes back as A2A artifact.

## Files to Create

```
python/src/roar_sdk/bridge.py           — BridgeRouter core
python/src/roar_sdk/adapters/mcp.py     — MCP ↔ ROAR adapter
python/src/roar_sdk/adapters/a2a.py     — A2A ↔ ROAR adapter
python/src/roar_sdk/dns_discovery.py    — DNS-AID + did:web + ANP
tests/test_bridge.py                    — Bridge integration tests
tests/test_mcp_adapter.py              — MCP adapter unit tests
tests/test_a2a_adapter.py              — A2A adapter unit tests
tests/test_dns_discovery.py            — DNS discovery tests
examples/demo/mcp_to_a2a_bridge.py     — Demo 1
examples/demo/cross_framework.py       — Demo 2
examples/demo/dns_discovery_bridge.py  — Demo 3
```

## Testing Strategy

- Unit: each adapter round-trips (MCP→ROAR→MCP, A2A→ROAR→A2A)
- Integration: Demo 1 as pytest (MCP in, A2A delivery, MCP response)
- E2E: Demo 3 with mock DNS
- Cross-SDK: TS helpers verify Python-bridged messages

## Success Criteria

- [ ] MCP `tools/call` reaches an A2A agent and returns a valid MCP result
- [ ] A2A `tasks/send` reaches a ROAR agent and returns a valid A2A artifact
- [ ] DNS-AID lookup discovers a ROAR hub and agents
- [ ] `did:web` resolution returns a valid DID Document with hub endpoint
- [ ] Protocol detection accuracy ≥ 99% across all supported protocols
- [ ] All existing 131 tests still pass
- [ ] 3 runnable demos (MCP→A2A, cross-framework, DNS→bridge)
