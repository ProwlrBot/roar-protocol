/**
 * ROAR Protocol — message creation, signing, and verification.
 *
 * Critical: pythonJsonDumps replicates Python's json.dumps(sort_keys=True)
 * including the float-formatting rule (integers get ".0" appended).
 * This ensures cross-language HMAC-SHA256 signatures are identical.
 */

import { createHmac, timingSafeEqual } from "crypto";
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
 * - Integers are formatted as floats: 1710000000 → "1710000000.0"
 * - Spacing: ", " between items, ": " between key and value (Python default)
 */
export function pythonJsonDumps(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "null";
    // Python json.dumps formats integer-valued floats with .0
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
 *
 * Covers all security-relevant fields with sorted keys:
 * context, from, id, intent, payload, timestamp, to
 *
 * The timestamp used is auth.timestamp (set during signing), not message.timestamp.
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
// Public API
// ---------------------------------------------------------------------------

/** Create an AgentIdentity with auto-generated DID if not provided. */
export function createIdentity(
  displayName: string,
  opts: Partial<{
    agentType: string;
    capabilities: string[];
    version: string;
    publicKey: string | null;
    did: string;
  }> = {},
): AgentIdentity {
  const agentType = opts.agentType ?? "agent";
  const slug = displayName.toLowerCase().replace(/\s+/g, "-").slice(0, 20) || "agent";
  const uid = randomHex(8); // 16 hex chars
  const did = opts.did || `did:roar:${agentType}:${slug}-${uid}`;

  return {
    did,
    display_name: displayName,
    agent_type: agentType,
    capabilities: opts.capabilities ?? [],
    version: opts.version ?? "1.0",
    public_key: opts.publicKey ?? null,
  };
}

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
 * Sign a ROARMessage with HMAC-SHA256.
 * Sets auth.timestamp and auth.signature. Returns the message (mutates in place).
 */
export function signMessage(msg: ROARMessage, secret: string): ROARMessage {
  msg.auth = { timestamp: Date.now() / 1000 };
  const body = signingBody(msg);
  const sig = createHmac("sha256", secret).update(body).digest("hex");
  msg.auth["signature"] = `hmac-sha256:${sig}`;
  return msg;
}

/**
 * Verify an HMAC-SHA256 signed ROARMessage.
 *
 * @param maxAgeSeconds - Maximum message age in seconds. 0 = skip age check.
 */
export function verifyMessage(
  msg: ROARMessage,
  secret: string,
  maxAgeSeconds = 300,
): boolean {
  const sigValue = (msg.auth["signature"] as string) ?? "";
  if (!sigValue.startsWith("hmac-sha256:")) return false;

  if (maxAgeSeconds > 0) {
    const msgTime = (msg.auth["timestamp"] as number) ?? 0;
    if (Math.abs(Date.now() / 1000 - msgTime) > maxAgeSeconds) return false;
  }

  const expected = sigValue.slice("hmac-sha256:".length);
  const body = signingBody(msg);
  const actual = createHmac("sha256", secret).update(body).digest("hex");

  // Constant-time comparison to prevent timing attacks
  try {
    return timingSafeEqual(Buffer.from(expected, "hex"), Buffer.from(actual, "hex"));
  } catch {
    return false;
  }
}
