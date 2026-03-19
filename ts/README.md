# @roar-protocol/sdk

> Routable Open Agent Runtime — TypeScript SDK

![Conformance](https://img.shields.io/badge/conformance-30%2F30-brightgreen) ![npm](https://img.shields.io/npm/v/@roar-protocol/sdk) ![License](https://img.shields.io/badge/license-MIT-blue) ![Node](https://img.shields.io/badge/node-%3E%3D18-green) ![Security](https://img.shields.io/badge/security-audited-brightgreen)

The TypeScript SDK for the ROAR Protocol. Build agents that can discover each other, exchange signed messages, stream events, and delegate capabilities — with zero external dependencies.

## Features

- Ed25519 identity + DID methods (`did:roar`, `did:key`, `did:web`)
- W3C DID Documents
- Cryptographic delegation tokens
- Graduated autonomy (`WATCH` → `GUIDE` → `DELEGATE` → `AUTONOMOUS`)
- HTTP + WebSocket + SSE + stdio transports
- AIMD backpressure event streaming
- TTL+LRU discovery cache + SQLite directory
- Protocol auto-detection (ROAR / MCP / A2A / ACP)
- Rate limiting + replay protection
- Zero external dependencies — Node.js 18+ built-ins only

## Install

```bash
npm install @roar-protocol/sdk
```

Requires Node.js 18 or later. No peer dependencies.

## Quick Start

```typescript
import {
  createIdentity,
  createMessage,
  signMessage,
  verifyMessage,
  ROARClient,
  MessageIntent,
  defaultConnectionConfig,
} from "@roar-protocol/sdk";

// 1. Create two agent identities
const sender = createIdentity("Alice", { agentType: "agent", capabilities: ["summarize"] });
const receiver = createIdentity("Bob",  { agentType: "tool",  capabilities: ["search"] });

// 2. Build a message
const msg = createMessage(
  sender,
  receiver,
  MessageIntent.EXECUTE,
  { text: "Summarize the ROAR spec." },
);

// 3. Sign it (HMAC-SHA256, cross-language compatible with the Python SDK)
const secret = "my-shared-secret";
signMessage(msg, secret);

// 4. Verify on the receiving side
const ok = verifyMessage(msg, secret); // true

// 5. Send over HTTP
const client = new ROARClient({
  ...defaultConnectionConfig(),
  url: "http://localhost:8080",
});
const response = await client.send(msg);
console.log(response.payload);
```

## Ed25519 Asymmetric Signing

```typescript
import {
  generateEd25519KeyPair,
  signEd25519,
  verifyEd25519,
  createIdentity,
} from "@roar-protocol/sdk";

const { privateKeyHex, publicKeyHex } = generateEd25519KeyPair();

const identity = createIdentity("Carol", {
  agentType: "agent",
  publicKey: publicKeyHex,
});
```

## Delegation Tokens

```typescript
import {
  issueToken,
  verifyAndValidateToken,
  AutonomyLevel,
} from "@roar-protocol/sdk";

const token = issueToken(
  issuerDid,
  subjectDid,
  ["read", "summarize"],
  { ttlSeconds: 3600, autonomyLevel: AutonomyLevel.DELEGATE },
);

const result = verifyAndValidateToken(token, issuerPublicKeyHex);
// result.valid === true
```

## Discovery Cache

```typescript
import { DiscoveryCache } from "@roar-protocol/sdk";

const cache = new DiscoveryCache({ maxEntries: 500, ttlSeconds: 300 });
cache.set(entry.agent_card.identity.did, entry);

const hit = cache.get("did:roar:agent:alice-abc123");
const stats = cache.stats(); // { size, hits, misses, evictions }
```

## Protocol Auto-Detection

```typescript
import { detectProtocol, normalizeToROAR } from "@roar-protocol/sdk";

const detected = detectProtocol(incomingPayload);
// detected.protocol: "roar" | "mcp" | "a2a" | "acp" | "unknown"

const roarMsg = normalizeToROAR(incomingPayload, senderIdentity, receiverIdentity);
```

## Protocol Layers

| Layer | Name | Exports |
|-------|------|---------|
| 1 | Identity | `createIdentity`, `generateEd25519KeyPair`, `issueToken`, `AutonomyLevel`, `DIDDocument`, `publicKeyToDidKey` |
| 2 | Discovery | `AgentDirectory`, `DiscoveryCache`, `SqliteAgentDirectory` |
| 3 | Connect | `ROARClient`, `ROARServer`, `ROARWebSocket`, `stdioSend`, `createROARRouter` |
| 4 | Exchange | `createMessage`, `signMessage`, `verifyMessage`, `detectProtocol`, `normalizeToROAR` |
| 5 | Stream | `EventBus`, `Subscription`, `StreamFilter` |

## Server

```typescript
import { createIdentity, ROARServer, MessageIntent } from "@roar-protocol/sdk";

const identity = createIdentity("MyAgent", { agentType: "agent", capabilities: ["search"] });
const server = new ROARServer(identity, {
  port: 8080,
  signingSecret: process.env.ROAR_SECRET,
});

// Register a handler per intent
server.on(MessageIntent.EXECUTE, async (msg) => {
  console.log("Task received:", msg.payload);
  return createMessage(identity, msg.from_identity, MessageIntent.RESPOND, { status: "ok" });
});

await server.start();
```

## Idempotency / Replay Protection

```typescript
import { IdempotencyGuard } from "@roar-protocol/sdk";

const guard = new IdempotencyGuard({ windowSeconds: 300, maxSize: 10_000 });

if (guard.is_duplicate(msg.id)) {
  // replay detected — discard
} else {
  // first time seen — process msg (key auto-recorded by is_duplicate)
}
```

## Security

The SDK was independently audited (see [`SECURITY-AUDIT-FINAL.md`](../SECURITY-AUDIT-FINAL.md) at the repo root). Key guarantees:

- All signature comparisons use `timingSafeEqual` from Node.js `crypto` — no timing oracle.
- No key material appears in error messages or logs.
- HMAC signing uses a canonical JSON serialization (`pythonJsonDumps`) that is byte-for-byte identical to the Python SDK, preventing cross-language signature mismatches.
- Delegation tokens carry TTL and autonomy level; `verifyAndValidateToken` rejects expired or out-of-scope tokens.
- `IdempotencyGuard` prevents replay attacks within a configurable time window.

## License

MIT — see [LICENSE](../LICENSE).
