/**
 * ROAR Protocol — Hub challenge-response authentication (TypeScript).
 * Mirrors python/src/roar_sdk/hub_auth.py.
 *
 * This in-memory store is single-process.
 * Distributed deployments should replace with Redis SETNX + TTL.
 */

import * as crypto from "crypto";

export interface PendingChallenge {
  challenge_id: string;
  did: string;
  nonce: string;
  expires_at: number;
  public_key: string; // hex Ed25519 public key
  card: Record<string, unknown>;
}

export class ChallengeStore {
  static readonly NONCE_TTL_SECONDS = 30.0;
  static readonly MAX_PENDING = 1000;

  private _pending = new Map<string, PendingChallenge>();

  issue(did: string, public_key: string, card: Record<string, unknown>): PendingChallenge {
    this._evictExpired();
    if (this._pending.size >= ChallengeStore.MAX_PENDING) {
      throw new Error("Too many pending challenges — server busy");
    }

    const challenge_id = crypto.randomBytes(16).toString("hex");
    const nonce = crypto.randomBytes(32).toString("hex");
    const expires_at = Date.now() / 1000 + ChallengeStore.NONCE_TTL_SECONDS;

    const ch: PendingChallenge = {
      challenge_id,
      did,
      nonce,
      expires_at,
      public_key,
      card,
    };

    this._pending.set(challenge_id, ch);
    return ch;
  }

  /** Return and DELETE the challenge (prevents replay). */
  consume(challenge_id: string): PendingChallenge | null {
    this._evictExpired();
    const ch = this._pending.get(challenge_id) ?? null;
    if (ch) this._pending.delete(challenge_id);
    return ch;
  }

  private _evictExpired(): void {
    const now = Date.now() / 1000;
    for (const [id, ch] of this._pending.entries()) {
      if (ch.expires_at < now) this._pending.delete(id);
    }
  }
}
