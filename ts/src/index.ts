/**
 * @roar-protocol/sdk — TypeScript SDK for the ROAR Protocol
 *
 * Re-exports all public APIs. Import from this file:
 *   import { createIdentity, createMessage, signMessage, ROARServer } from "@roar-protocol/sdk"
 */

// Types (Layer 1-5)
export type {
  AgentIdentity,
  AgentCapability,
  AgentCard,
  DiscoveryEntry,
  ConnectionConfig,
  ROARMessage,
  StreamEvent,
} from "./types.js";

export {
  AgentDirectory,
  TransportType,
  MessageIntent,
  StreamEventType,
  messageFromWire,
  messageToWire,
  defaultConnectionConfig,
  randomHex,
} from "./types.js";

// Message creation and signing (Layer 4)
export {
  createIdentity,
  createMessage,
  signMessage,
  verifyMessage,
  pythonJsonDumps,
} from "./message.js";

// Server (Layer 3-4)
export { ROARServer } from "./server.js";
export type { ROARServerOptions } from "./server.js";

// Client (Layer 3)
export { ROARClient } from "./client.js";

// WebSocket transport (Layer 3)
export { ROARWebSocket } from "./websocket.js";

// Streaming (Layer 5)
export { EventBus, Subscription, StreamFilter } from "./streaming.js";
export type { StreamFilterSpec } from "./streaming.js";

// Ed25519 signing (Layer 1 — asymmetric)
export {
  generateEd25519KeyPair,
  signEd25519,
  verifyEd25519,
} from "./signing.js";
export type { Ed25519KeyPair } from "./signing.js";

// Delegation tokens (Layer 1 — capability grants)
export {
  issueToken,
  verifyToken,
  isTokenValid,
  tokenGrants,
  consumeToken,
} from "./delegation.js";
export type { DelegationToken } from "./delegation.js";

// Idempotency / replay protection
export { IdempotencyGuard } from "./dedup.js";

// stdio transport (Layer 3 — newline-delimited JSON over stdin/stdout)
export { stdioSend } from "./stdio.js";

// SQLite-backed persistent directory (Layer 2)
export { SqliteAgentDirectory } from "./sqlite_directory.js";

// Router (SSE + WebSocket + rate limiting)
export { createROARRouter } from "./router.js";
export type { ROARRouter, ROARRouterOptions } from "./router.js";

// DID methods (Layer 1 — identity)
export { publicKeyToDidKey, didKeyToPublicKey } from "./did_key.js";
export { urlToDidWeb, didWebToUrl } from "./did_web.js";

// Protocol auto-detection (Layer 4)
export { detectProtocol, normalizeToROAR } from "./detect.js";
export type { DetectedProtocol } from "./detect.js";
