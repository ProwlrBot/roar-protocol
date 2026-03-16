/**
 * ROAR Protocol — strict reference verifier.
 *
 * Mirrors python/src/roar_sdk/verifier.py exactly.
 *
 * Layers replay checks, recipient binding, and strict directional timestamp
 * enforcement on top of signature verification. Intended for production receivers.
 */

import { IdempotencyGuard } from "./dedup.js";
import { verifyMessage } from "./message.js";
import { verifyEd25519 } from "./signing.js";
import type { ROARMessage } from "./types.js";

// ---------------------------------------------------------------------------
// VerificationResult
// ---------------------------------------------------------------------------

export interface VerificationResult {
  readonly ok: boolean;
  readonly error: string;
}

function ok(): VerificationResult {
  return { ok: true, error: "" };
}

function fail(error: string): VerificationResult {
  return { ok: false, error };
}

// ---------------------------------------------------------------------------
// StrictMessageVerifier
// ---------------------------------------------------------------------------

export interface StrictMessageVerifierOptions {
  /** HMAC secret. Required when verifying hmac-sha256 messages. */
  hmacSecret?: string;
  /** If set, `msg.to_identity.did` must match this value. */
  expectedRecipientDid?: string;
  /** Maximum message age in seconds. Default: 300. */
  maxAgeSeconds?: number;
  /** Maximum future skew in seconds. Default: 30. */
  maxFutureSkewSeconds?: number;
  /** Replay guard instance. If omitted, replay detection is skipped. */
  replayGuard?: IdempotencyGuard;
  /** Allowed signature schemes. Default: ["hmac-sha256", "ed25519"]. */
  allowedSignatureSchemes?: readonly string[];
}

/**
 * Reference message verifier with explicit security policy.
 *
 * Policy defaults are intentionally strict and should be tuned only with care.
 *
 * @example
 * ```ts
 * const verifier = new StrictMessageVerifier({
 *   hmacSecret: process.env.ROAR_SECRET!,
 *   expectedRecipientDid: myAgent.did,
 *   replayGuard: new IdempotencyGuard(),
 * });
 *
 * const result = verifier.verify(msg);
 * if (!result.ok) throw new Error(result.error);
 * ```
 */
export class StrictMessageVerifier {
  private readonly _hmacSecret: string;
  private readonly _expectedRecipientDid: string | undefined;
  private readonly _maxAge: number;
  private readonly _maxFutureSkew: number;
  private readonly _replayGuard: IdempotencyGuard | undefined;
  private readonly _allowed: ReadonlySet<string>;

  constructor(options: StrictMessageVerifierOptions = {}) {
    this._hmacSecret = options.hmacSecret ?? "";
    this._expectedRecipientDid = options.expectedRecipientDid;
    this._maxAge = options.maxAgeSeconds ?? 300;
    this._maxFutureSkew = options.maxFutureSkewSeconds ?? 30;
    this._replayGuard = options.replayGuard;
    this._allowed = new Set(
      options.allowedSignatureSchemes ?? ["hmac-sha256", "ed25519"],
    );
  }

  verify(msg: ROARMessage): VerificationResult {
    // 1. Signature field must exist and be scheme:value
    const sigValue = msg.auth["signature"];
    if (typeof sigValue !== "string" || !sigValue.includes(":")) {
      return fail("missing_or_invalid_signature");
    }

    const scheme = sigValue.split(":")[0];

    // 2. Scheme allowlist
    if (!this._allowed.has(scheme)) {
      return fail("signature_scheme_not_allowed");
    }

    // 3. Recipient binding
    if (
      this._expectedRecipientDid &&
      msg.to_identity.did !== this._expectedRecipientDid
    ) {
      return fail("recipient_mismatch");
    }

    // 4. Timestamp — must exist and be numeric
    const ts = msg.auth["timestamp"];
    if (typeof ts !== "number") {
      return fail("missing_or_invalid_auth_timestamp");
    }

    // 5. Directional timestamp checks (no Math.abs — direction matters)
    const now = Date.now() / 1000;
    const age = now - ts;
    if (age > this._maxAge) {
      return fail("message_expired");
    }
    if (-age > this._maxFutureSkew) {
      return fail("message_from_future");
    }

    // 6. Replay detection
    if (this._replayGuard !== undefined && this._replayGuard.is_duplicate(msg.id)) {
      return fail("replay_detected");
    }

    // 7. Signature verification — pass maxAgeSeconds=0 to skip their internal
    //    age check (we already enforced it above with directional logic)
    if (scheme === "hmac-sha256") {
      if (!this._hmacSecret) {
        return fail("missing_hmac_secret");
      }
      if (!verifyMessage(msg, this._hmacSecret, 0)) {
        return fail("invalid_hmac_signature");
      }
      return ok();
    }

    if (scheme === "ed25519") {
      if (!verifyEd25519(msg, 0)) {
        return fail("invalid_ed25519_signature");
      }
      return ok();
    }

    return fail("unsupported_signature_scheme");
  }
}
