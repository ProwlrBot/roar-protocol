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
