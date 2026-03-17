/**
 * @roar-protocol/sdk-browser — Browser/WASM SDK for the ROAR Protocol
 *
 * This is the browser-compatible version of the ROAR Protocol SDK.
 * It uses the Web Crypto API instead of Node.js crypto built-ins.
 *
 * Key differences from the Node SDK (@roar-protocol/sdk):
 * - All signing/verification functions are async (Web Crypto is async)
 * - No fs/net/stdio dependencies
 * - Ed25519 key generation is async
 * - Uses signMessageAsync/verifyMessageAsync instead of signMessage/verifyMessage
 *
 * Usage:
 *   import { createIdentity, createMessage, signMessageAsync } from "@roar-protocol/sdk-browser"
 */

// Types (Layer 1-5)
export type {
  AgentIdentity,
  AgentCapability,
  AgentCard,
  DiscoveryEntry,
  ROARMessage,
  StreamEvent,
} from "./types.js";

export {
  AgentDirectory,
  MessageIntent,
  StreamEventType,
  randomHex,
  createIdentity,
} from "./types.js";

// Message creation and signing (Layer 4 — async Web Crypto)
export {
  createMessage,
  signMessageAsync,
  verifyMessageAsync,
  pythonJsonDumps,
} from "./message.js";

// Ed25519 signing (Layer 1 — async Web Crypto)
export {
  generateKeyPair,
  signEd25519,
  verifyEd25519,
} from "./signing.js";
export type { Ed25519KeyPair } from "./signing.js";
