/**
 * ROAR Protocol — Capability delegation tokens.
 *
 * Mirrors python/src/roar_sdk/delegation.py exactly.
 * Uses Node.js 18+ built-in crypto — no external dependencies.
 *
 * Signing format: Ed25519 over canonical JSON of token fields
 * (same sort-keys approach as HMAC message signing).
 */

import {
  createPrivateKey,
  createPublicKey,
  sign as cryptoSign,
  verify as cryptoVerify,
  randomBytes,
} from "crypto";

// ---------------------------------------------------------------------------
// Canonical JSON (sort keys, mirrors Python json.dumps(sort_keys=True))
// ---------------------------------------------------------------------------

function sortedJson(value: unknown): string {
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
    return "[" + value.map(sortedJson).join(", ") + "]";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    if (keys.length === 0) return "{}";
    const pairs = keys.map(
      (k) => `${JSON.stringify(k)}: ${sortedJson((value as Record<string, unknown>)[k])}`
    );
    return "{" + pairs.join(", ") + "}";
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// DER key helpers (same as signing.ts)
// ---------------------------------------------------------------------------

function privateKeyFromHex(hex: string): ReturnType<typeof createPrivateKey> {
  const raw = Buffer.from(hex, "hex");
  const pkcs8Header = Buffer.from("302e020100300506032b657004220420", "hex");
  return createPrivateKey({
    key: Buffer.concat([pkcs8Header, raw]),
    format: "der",
    type: "pkcs8",
  });
}

function publicKeyFromHex(hex: string): ReturnType<typeof createPublicKey> {
  const raw = Buffer.from(hex, "hex");
  const spkiHeader = Buffer.from("302a300506032b6570032100", "hex");
  return createPublicKey({
    key: Buffer.concat([spkiHeader, raw]),
    format: "der",
    type: "spki",
  });
}

// ---------------------------------------------------------------------------
// DelegationToken
// ---------------------------------------------------------------------------

export interface DelegationToken {
  /** "tok_" + 10 random hex chars */
  token_id: string;
  delegator_did: string;
  delegate_did: string;
  capabilities: string[];
  issued_at: number;
  expires_at: number | null;
  max_uses: number | null;
  use_count: number;
  can_redelegate: boolean;
  signature: string;
}

/** Return true if the token has not expired and has remaining uses. */
export function isTokenValid(token: DelegationToken): boolean {
  const now = Date.now() / 1000;
  if (token.expires_at !== null && now > token.expires_at) return false;
  if (token.max_uses !== null && token.use_count >= token.max_uses) return false;
  return true;
}

/** Return true if the token grants the requested capability. */
export function tokenGrants(token: DelegationToken, capability: string): boolean {
  return token.capabilities.includes(capability) || token.capabilities.includes("*");
}

/**
 * Atomically check validity and consume one use of the token (increment use_count).
 * Returns true if use was recorded, false if the token is exhausted.
 *
 * This is a single synchronous check+increment with no await between them,
 * making it safe against TOCTOU in JS's single-threaded event loop.
 * Do NOT call isTokenValid() separately before this — use verifyAndValidateToken()
 * to combine signature + validity + consume in one logical step.
 */
export function consumeToken(token: DelegationToken): boolean {
  if (token.max_uses !== null && token.use_count >= token.max_uses) return false;
  token.use_count += 1;
  return true;
}

// ---------------------------------------------------------------------------
// Signing body — all fields except `signature` and `use_count`
// ---------------------------------------------------------------------------

function signingBody(token: DelegationToken): Buffer {
  const body: Record<string, unknown> = {
    token_id: token.token_id,
    delegator_did: token.delegator_did,
    delegate_did: token.delegate_did,
    capabilities: token.capabilities,
    issued_at: token.issued_at,
    expires_at: token.expires_at,
    max_uses: token.max_uses,
    can_redelegate: token.can_redelegate,
  };
  return Buffer.from(sortedJson(body), "utf-8");
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Issue a new DelegationToken signed by the delegator's Ed25519 private key.
 *
 * @param delegatorDid        - DID of the issuing agent
 * @param delegatorPrivateKey - 32-byte raw private key as hex
 * @param delegateDid         - DID of the recipient agent
 * @param capabilities        - list of capability strings (e.g. ["read", "write"])
 * @param expiresInSeconds    - TTL from now (default 3600). 0 = no expiry.
 * @param maxUses             - optional hard use cap
 * @param canRedelegate       - whether the delegate may further delegate
 */
export function issueToken(
  delegatorDid: string,
  delegatorPrivateKey: string,
  delegateDid: string,
  capabilities: string[],
  expiresInSeconds = 3600,
  maxUses: number | null = null,
  canRedelegate = false,
): DelegationToken {
  const now = Date.now() / 1000;
  const token: DelegationToken = {
    token_id: "tok_" + randomBytes(5).toString("hex"),
    delegator_did: delegatorDid,
    delegate_did: delegateDid,
    capabilities,
    issued_at: now,
    expires_at: expiresInSeconds > 0 ? now + expiresInSeconds : null,
    max_uses: maxUses,
    use_count: 0,
    can_redelegate: canRedelegate,
    signature: "",
  };

  const privKey = privateKeyFromHex(delegatorPrivateKey);
  const rawSig = cryptoSign(null, signingBody(token), privKey) as Buffer;
  token.signature = "ed25519:" + rawSig.toString("base64url");
  return token;
}

/**
 * Verify a DelegationToken's Ed25519 signature only.
 *
 * @param token               - the token to verify
 * @param delegatorPublicKey  - 32-byte raw public key as hex (must match token.delegator_did's key)
 * @returns true if signature is cryptographically valid
 * @note Does NOT check expiry or use count — use verifyAndValidateToken for full validation.
 */
export function verifyToken(token: DelegationToken, delegatorPublicKey: string): boolean {
  if (!token.signature.startsWith("ed25519:")) return false;
  try {
    const pubKey = publicKeyFromHex(delegatorPublicKey);
    const b64 = token.signature.slice("ed25519:".length);
    const rawSig = Buffer.from(b64, "base64url");
    return cryptoVerify(null, signingBody(token), pubKey, rawSig) as boolean;
  } catch {
    return false;
  }
}

/**
 * Verify signature AND check that the token is not expired or exhausted.
 * Prefer this over calling verifyToken + isTokenValid separately (avoids TOCTOU).
 *
 * @returns true only if signature valid AND not expired AND uses remaining
 */
export function verifyAndValidateToken(token: DelegationToken, delegatorPublicKey: string): boolean {
  return verifyToken(token, delegatorPublicKey) && isTokenValid(token);
}
