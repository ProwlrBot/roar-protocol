# ROAR TypeScript Examples

Minimal examples showing ROAR agent communication using the TypeScript SDK.

---

## Prerequisites

The TypeScript examples import from `@roar-protocol/sdk`. Install the package or build from source:

```bash
# Install from npm
npm install @roar-protocol/sdk

# OR build from source (from the repo root):
cd ts && npm ci && npm run build && cd ..

# Run with ts-node (no build needed):
npm install -g ts-node   # once
# or: curl -fsSL https://bun.sh/install | bash
```

---

## Run the Echo Server

```bash
# Terminal 1 — start the server
npx ts-node examples/ts/echo_server.ts

# Expected output:
# Server DID: did:roar:agent:echo-server-xxxxxxxx
# ROAR echo server listening on http://127.0.0.1:8089
```

## Run the Client

```bash
# Terminal 2 — send a DELEGATE message
npx ts-node examples/ts/client.ts

# Expected output:
# Client DID: did:roar:agent:ts-client-xxxxxxxx
# → Sending DELEGATE message:
#   id:      msg_xxxxxxxxxxxx
#   intent:  delegate
#   payload: { task: 'reflect this payload back to me', priority: 'low' }
#   signed:  true
# ← Response received:
#   intent:  respond
#   payload: { echo: { task: '...', priority: 'low' }, status: 'ok' }
#   sig ok:  true
# ROAR round-trip complete.
```

---

## Files

| File | Description |
|------|-------------|
| `echo_server.ts` | Minimal HTTP server receiving ROAR messages |
| `client.ts` | Creates an identity, signs a DELEGATE, sends it, verifies the response |

---

## See Also

- [Python examples](../python/) — same flow in Python
- [SDK-ROADMAP.md](../../SDK-ROADMAP.md) — open tasks and divergence tracker
- [ROAR-SPEC.md](../../ROAR-SPEC.md) — full protocol specification
