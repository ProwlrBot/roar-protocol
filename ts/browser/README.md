# @roar-protocol/sdk-browser

Browser/WASM SDK for the [ROAR Protocol](https://github.com/ProwlrBot/roar-protocol) (Routable Open Agent Runtime).

This is the browser-compatible version of the ROAR Protocol TypeScript SDK. It replaces Node.js `crypto` built-ins with the [Web Crypto API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Crypto_API) and removes all `fs`/`net` dependencies.

## Installation

```bash
npm install @roar-protocol/sdk-browser
```

## Usage

```typescript
import {
  createIdentity,
  createMessage,
  signMessageAsync,
  verifyMessageAsync,
  generateKeyPair,
  signEd25519,
  verifyEd25519,
  MessageIntent,
  AgentDirectory,
} from "@roar-protocol/sdk-browser";

// Create agent identities
const alice = createIdentity("Alice", {
  agentType: "agent",
  capabilities: ["chat", "search"],
});
const bob = createIdentity("Bob", { agentType: "tool" });

// Create and sign a message (HMAC-SHA256)
const msg = createMessage(alice, bob, MessageIntent.EXECUTE, {
  action: "search",
  query: "ROAR protocol",
});
const signed = await signMessageAsync(msg, "shared-secret");

// Verify the signature
const valid = await verifyMessageAsync(signed, "shared-secret");
console.log("Valid:", valid); // true

// Ed25519 asymmetric signing
const keyPair = await generateKeyPair();
const edMsg = createMessage(alice, bob, MessageIntent.ASK, { question: "Hello?" });
const edSigned = await signEd25519(edMsg, keyPair.privateKeyHex);
const edValid = await verifyEd25519(edSigned, 0, keyPair.publicKeyHex);
```

## CDN Usage

```html
<script type="module">
  import {
    createIdentity,
    createMessage,
    signMessageAsync,
    MessageIntent,
  } from "https://unpkg.com/@roar-protocol/sdk-browser/dist/index.js";

  const agent = createIdentity("MyAgent");
  // ...
</script>
```

## Differences from the Node SDK

| Feature | Node SDK (`@roar-protocol/sdk`) | Browser SDK (`@roar-protocol/sdk-browser`) |
|---|---|---|
| Signing | `signMessage()` (sync) | `signMessageAsync()` (async) |
| Verification | `verifyMessage()` (sync) | `verifyMessageAsync()` (async) |
| Ed25519 keygen | `generateEd25519KeyPair()` (sync) | `generateKeyPair()` (async) |
| Ed25519 sign | `signEd25519()` (sync) | `signEd25519()` (async, returns Promise) |
| Ed25519 verify | `verifyEd25519()` (sync) | `verifyEd25519()` (async, returns Promise) |
| Crypto backend | Node.js `crypto` module | Web Crypto API (`SubtleCrypto`) |
| Transport | HTTP, WebSocket, stdio, gRPC | None (bring your own fetch/WebSocket) |
| File system | SQLite directory, file I/O | In-memory `AgentDirectory` only |
| Server | `ROARServer`, `createROARRouter` | Not included |

## Browser Compatibility

- **HMAC-SHA256**: All modern browsers (Chrome, Firefox, Safari, Edge)
- **Ed25519**: Chrome 113+, Edge 113+, Firefox 130+, Safari 17+

## Building from Source

```bash
npm install
npm run build
```

The build uses [esbuild](https://esbuild.github.io/) to produce a single ESM bundle at `dist/index.js`.

## Testing

Open `src/test.html` in a browser after building. It runs a suite of tests covering identity creation, message signing, Ed25519 operations, and the agent directory.

## License

MIT
