/**
 * ROAR Protocol — Browser SDK message creation, signing, and verification.
 *
 * Uses the Web Crypto API (SubtleCrypto) instead of Node.js crypto.
 * All signing/verification functions are async because Web Crypto is async.
 *
 * pythonJsonDumps replicates Python's json.dumps(sort_keys=True) including
 * the float-formatting rule so cross-language HMAC-SHA256 signatures match.
 */

import {
  AgentIdentity,
  MessageIntent,
  ROARMessage,
  randomHex,
} from "./types.js";

// ---------------------------------------------------------------------------
// pythonJsonDumps — replicates json.dumps(value, sort_keys=True)
// ---------------------------------------------------------------------------

/**
 * Produce the same JSON string as Python's json.dumps(value, sort_keys=True).
 *
 * Key differences from JSON.stringify:
 * - Object keys are sorted alphabetically (recursively)
 * - Integers are formatted as floats: 1710000000 -> "1710000000.0"
 * - Spacing: ", " between items, ": " between key and value (Python default)
 */
export function pythonJsonDumps(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "null";
    if (Number.isInteger(value)) return `${value}.0`;
    return String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return "[" + value.map(pythonJsonDumps).join(", ") + "]";
  }
  if (typeof value === "object" && value !== null) {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    if (keys.length === 0) return "{}";
    const pairs = keys.map(
      (k) =>
        `${JSON.stringify(k)}: ${pythonJsonDumps((value as Record<string, unknown>)[k])}`,
    );
    return "{" + pairs.join(", ") + "}";
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// Signing canonical body
// ---------------------------------------------------------------------------

/**
 * Produce the canonical JSON body for HMAC signing.
 * Covers all security-relevant fields with sorted keys.
 */
function signingBody(msg: ROARMessage): string {
  const body: Record<string, unknown> = {
    id: msg.id,
    from: msg.from_identity.did,
    to: msg.to_identity.did,
    intent: msg.intent,
    payload: msg.payload,
    context: msg.context,
    timestamp: (msg.auth["timestamp"] as number) ?? msg.timestamp,
  };
  return pythonJsonDumps(body);
}

// ---------------------------------------------------------------------------
// Encoding helpers
// ---------------------------------------------------------------------------

const encoder = new TextEncoder();

/** Convert an ArrayBuffer to a hex string. */
function bufferToHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

/** Convert a hex string to a Uint8Array. */
function hexToBuffer(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Create a new ROARMessage with auto-generated id and timestamp. */
export function createMessage(
  from: AgentIdentity,
  to: AgentIdentity,
  intent: MessageIntent,
  payload: Record<string, unknown> = {},
  context: Record<string, unknown> = {},
): ROARMessage {
  return {
    roar: "1.0",
    id: `msg_${randomHex(5)}`, // 10 hex chars
    from_identity: from,
    to_identity: to,
    intent,
    payload,
    context,
    auth: {},
    timestamp: Date.now() / 1000,
  };
}

/**
 * Sign a ROARMessage with HMAC-SHA256 using the Web Crypto API.
 *
 * This is async because Web Crypto operations are async.
 * Sets auth.timestamp and auth.signature. Returns the message (mutates in place).
 */
export async function signMessageAsync(
  msg: ROARMessage,
  secret: string,
): Promise<ROARMessage> {
  msg.auth = { timestamp: Date.now() / 1000 };
  const body = signingBody(msg);

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  const sigHex = bufferToHex(signature);
  msg.auth["signature"] = `hmac-sha256:${sigHex}`;
  return msg;
}

/**
 * Verify an HMAC-SHA256 signed ROARMessage using the Web Crypto API.
 *
 * This is async because Web Crypto operations are async.
 *
 * @param maxAgeSeconds - Maximum message age in seconds. 0 = skip age check.
 */
export async function verifyMessageAsync(
  msg: ROARMessage,
  secret: string,
  maxAgeSeconds = 300,
): Promise<boolean> {
  const sigValue = (msg.auth["signature"] as string) ?? "";
  if (!sigValue.startsWith("hmac-sha256:")) return false;

  if (maxAgeSeconds > 0) {
    const msgTime = (msg.auth["timestamp"] as number) ?? 0;
    if (Math.abs(Date.now() / 1000 - msgTime) > maxAgeSeconds) return false;
  }

  const expected = sigValue.slice("hmac-sha256:".length);
  const body = signingBody(msg);

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );

  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  const actual = bufferToHex(signature);

  // Constant-length comparison (not truly constant-time in JS, but
  // avoids early-exit on first mismatch which is the main timing vector)
  if (expected.length !== actual.length) return false;
  let result = 0;
  for (let i = 0; i < expected.length; i++) {
    result |= expected.charCodeAt(i) ^ actual.charCodeAt(i);
  }
  return result === 0;
}
