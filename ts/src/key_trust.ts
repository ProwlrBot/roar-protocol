/**
 * ROAR Protocol — Ed25519 key trust enforcement (TypeScript).
 *
 * Mirrors python/src/roar_sdk/key_trust.py exactly.
 *
 * Security invariants:
 *   - Public keys MUST be resolved from trusted sources (DID documents, hub registry)
 *   - Public keys from message auth headers MUST NOT be trusted (attacker-controlled)
 *   - Key rotation MUST support backward compatibility windows
 *   - Expired keys MUST be rejected even if cryptographically valid
 */

import { verifyEd25519 } from "./signing.js";
import type { ROARMessage } from "./types.js";

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

export interface KeyMetadata {
  publicKeyHex: string;
  did: string;
  createdAt: number;
  expiresAt: number | null;
  rotatedAt: number | null;
  replacedBy: string | null; // publicKeyHex of successor
  source: string; // "manual", "hub", "did_document", "challenge_response"
}

export interface KeyTrustResult {
  trusted: boolean;
  error: string;
  keyMetadata: KeyMetadata | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isExpired(key: KeyMetadata): boolean {
  if (key.expiresAt === null) return false;
  return Date.now() / 1000 > key.expiresAt;
}

function isRotated(key: KeyMetadata): boolean {
  return key.replacedBy !== null;
}

function ageHours(key: KeyMetadata): number {
  return (Date.now() / 1000 - key.createdAt) / 3600;
}

// ---------------------------------------------------------------------------
// KeyTrustStore
// ---------------------------------------------------------------------------

export interface KeyTrustStoreOptions {
  defaultMaxAgeHours?: number; // default 720 (30 days)
  rotationGraceHours?: number; // default 24
}

/**
 * Manages trusted public keys for Ed25519 verification.
 *
 * Security policy:
 *   - Only keys explicitly registered or resolved from trusted sources are accepted
 *   - Keys have mandatory expiration (default 30 days)
 *   - Rotated keys remain valid during a grace period for in-flight messages
 *   - Keys from message auth headers (attacker-controlled) are NEVER trusted
 */
export class KeyTrustStore {
  private readonly defaultMaxAge: number;
  private readonly rotationGrace: number;
  private readonly keys: Map<string, KeyMetadata[]> = new Map();

  constructor(opts: KeyTrustStoreOptions = {}) {
    this.defaultMaxAge = opts.defaultMaxAgeHours ?? 720;
    this.rotationGrace = opts.rotationGraceHours ?? 24;
  }

  /**
   * Register a trusted public key for a DID.
   */
  registerKey(
    did: string,
    publicKeyHex: string,
    opts: { maxAgeHours?: number; source?: string } = {},
  ): KeyMetadata {
    if (publicKeyHex.length !== 64) {
      throw new Error(
        `Invalid public key length: expected 64 hex chars, got ${publicKeyHex.length}`,
      );
    }
    if (!/^[0-9a-f]+$/i.test(publicKeyHex)) {
      throw new Error("Invalid public key: not valid hex");
    }

    const lifetime = (opts.maxAgeHours ?? this.defaultMaxAge) * 3600;
    const now = Date.now() / 1000;

    const meta: KeyMetadata = {
      publicKeyHex,
      did,
      createdAt: now,
      expiresAt: now + lifetime,
      rotatedAt: null,
      replacedBy: null,
      source: opts.source ?? "manual",
    };

    if (!this.keys.has(did)) {
      this.keys.set(did, []);
    }
    this.keys.get(did)!.unshift(meta); // newest first
    return meta;
  }

  /**
   * Rotate a DID's key — old key enters grace period, new key becomes active.
   */
  rotateKey(
    did: string,
    newPublicKeyHex: string,
    opts: { source?: string } = {},
  ): KeyMetadata {
    const now = Date.now() / 1000;
    const currentKeys = this.keys.get(did) ?? [];

    for (const key of currentKeys) {
      if (!isExpired(key) && !isRotated(key)) {
        key.rotatedAt = now;
        key.replacedBy = newPublicKeyHex;
        key.expiresAt = now + this.rotationGrace * 3600;
        break;
      }
    }

    return this.registerKey(did, newPublicKeyHex, {
      source: opts.source ?? "rotation",
    });
  }

  /**
   * Get the current trusted public key for a DID.
   * Returns the newest non-expired, non-rotated key.
   */
  getTrustedKey(did: string): KeyTrustResult {
    const keys = this.keys.get(did);
    if (!keys || keys.length === 0) {
      return { trusted: false, error: `no_keys_registered_for_${did}`, keyMetadata: null };
    }

    for (const key of keys) {
      if (isExpired(key)) continue;
      if (isRotated(key)) continue;
      return { trusted: true, error: "", keyMetadata: key };
    }

    return { trusted: false, error: "all_keys_expired_or_rotated", keyMetadata: null };
  }

  /**
   * Check if a specific public key is trusted for a DID.
   * Accepts both active keys and keys in rotation grace period.
   */
  isKeyTrusted(did: string, publicKeyHex: string): KeyTrustResult {
    const keys = this.keys.get(did);
    if (!keys || keys.length === 0) {
      return { trusted: false, error: "no_keys_registered", keyMetadata: null };
    }

    for (const key of keys) {
      if (key.publicKeyHex !== publicKeyHex) continue;
      if (isExpired(key)) {
        return { trusted: false, error: "key_expired", keyMetadata: null };
      }
      return { trusted: true, error: "", keyMetadata: key };
    }

    return { trusted: false, error: "key_not_in_trust_store", keyMetadata: null };
  }

  /**
   * Verify a message's Ed25519 signature against the trust store.
   *
   * SECURITY: This method NEVER uses auth.public_key from the message.
   * It only uses keys registered in the trust store for the sender's DID.
   */
  verifyMessage(msg: ROARMessage): KeyTrustResult {
    const sig = msg.auth?.signature ?? "";
    if (typeof sig !== "string" || !sig.startsWith("ed25519:")) {
      return { trusted: false, error: "not_ed25519_signature", keyMetadata: null };
    }

    const senderDid = msg.from_identity.did;
    const keys = this.keys.get(senderDid);

    if (!keys || keys.length === 0) {
      return {
        trusted: false,
        error: `no_trusted_keys_for_${senderDid}`,
        keyMetadata: null,
      };
    }

    // Try each non-expired key (supports rotation grace period)
    for (const key of keys) {
      if (isExpired(key)) continue;
      if (verifyEd25519(msg, 0, key.publicKeyHex)) {
        return { trusted: true, error: "", keyMetadata: key };
      }
    }

    return {
      trusted: false,
      error: "signature_not_valid_with_any_trusted_key",
      keyMetadata: null,
    };
  }

  /**
   * Remove all expired keys from the store.
   */
  purgeExpired(): number {
    let purged = 0;
    for (const [did, keys] of this.keys.entries()) {
      const before = keys.length;
      const remaining = keys.filter((k) => !isExpired(k));
      purged += before - remaining.length;
      if (remaining.length === 0) {
        this.keys.delete(did);
      } else {
        this.keys.set(did, remaining);
      }
    }
    return purged;
  }

  /**
   * List all keys (including expired) for a DID.
   */
  listKeys(did: string): KeyMetadata[] {
    return [...(this.keys.get(did) ?? [])];
  }
}
