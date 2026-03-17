# ROAR Protocol — Live Demo

Two agents discover each other through a hub and exchange messages.

## Architecture

```
Terminal 1                Terminal 2                Terminal 3
┌──────────┐             ┌──────────┐             ┌──────────┐
│  HUB     │             │ AGENT A  │             │ AGENT B  │
│  :8090   │◄──register──│  :8091   │             │ (client) │
│          │◄──register──│          │◄────────────│          │
│          │──discover──►│          │  DELEGATE   │          │
│          │             │          │────────────►│          │
│          │             │          │  RESPOND    │          │
│          │             │          │◄────────────│          │
└──────────┘             └──────────┘             └──────────┘
  Discovery               Coder Agent             Tester Agent
  Server                  (code-review)            (testing, qa)
```

## How to Run

### Terminal 1 — Start the Hub
```bash
cd roar-protocol
pip install -e "python/.[server,ed25519]"
python examples/demo/hub.py
```

### Terminal 2 — Start Agent A (Coder)
```bash
python examples/demo/agent_a.py
```
Agent A registers with the hub, then listens for messages.

### Terminal 3 — Run Agent B (Tester)
```bash
python examples/demo/agent_b.py
```
Agent B registers, discovers Agent A via the hub, sends a code review request, and gets a response.

## What You'll See

1. **Hub** logs agent registrations
2. **Agent A** registers via Ed25519 challenge-response, starts listening
3. **Agent B** registers, searches hub for "code-review" capability, finds Agent A
4. **Agent B** sends a signed DELEGATE message to Agent A
5. **Agent A** receives it, logs the payload, sends back a RESPOND
6. **Agent B** displays the response

## The Flow (ROAR Protocol Layers)

| Step | Layer | What Happens |
|------|-------|-------------|
| 1 | Layer 1 (Identity) | Both agents generate Ed25519 keypairs and DIDs |
| 2 | Layer 2 (Discovery) | Agents register with hub via challenge-response |
| 3 | Layer 2 (Discovery) | Agent B searches hub for "code-review" capability |
| 4 | Layer 3 (Connect) | Agent B gets Agent A's HTTP endpoint from hub |
| 5 | Layer 4 (Exchange) | Agent B sends HMAC-signed DELEGATE message |
| 6 | Layer 4 (Exchange) | Agent A verifies signature, processes, responds |
