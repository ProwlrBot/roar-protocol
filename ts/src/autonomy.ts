/**
 * Graduated autonomy model and runtime capability delegation (Layer 1).
 *
 * Agents operate at different trust levels. The AutonomyLevel ladder defines
 * how much independent action an agent can take. CapabilityDelegation manages
 * in-memory grant/revoke/check at runtime.
 *
 * This is distinct from DelegationToken (delegation.ts), which is a
 * cryptographic artifact that travels with messages and can be verified by
 * third parties without contacting the issuer. CapabilityDelegation is the
 * server-side policy engine that enforces who can do what.
 *
 * Autonomy levels (from design doc):
 *   WATCH      — observe only, no actions
 *   GUIDE      — suggest actions for human approval
 *   DELEGATE   — act on specific delegated capabilities
 *   AUTONOMOUS — act freely within declared capabilities
 */

import { randomBytes } from "crypto";

// ---------------------------------------------------------------------------
// AutonomyLevel
// ---------------------------------------------------------------------------

export const AutonomyLevel = {
  WATCH: "watch",
  GUIDE: "guide",
  DELEGATE: "delegate",
  AUTONOMOUS: "autonomous",
} as const;

export type AutonomyLevel = (typeof AutonomyLevel)[keyof typeof AutonomyLevel];

/** Ordered list used for level comparison by index (lowest → highest). */
const _AUTONOMY_ORDER: AutonomyLevel[] = [
  AutonomyLevel.WATCH,
  AutonomyLevel.GUIDE,
  AutonomyLevel.DELEGATE,
  AutonomyLevel.AUTONOMOUS,
];

/** True if this level allows the agent to take actions without approval. */
export function autonomyCanAct(level: AutonomyLevel): boolean {
  return level === AutonomyLevel.DELEGATE || level === AutonomyLevel.AUTONOMOUS;
}

/** True if actions at this level need human approval. */
export function autonomyRequiresApproval(level: AutonomyLevel): boolean {
  return level === AutonomyLevel.WATCH || level === AutonomyLevel.GUIDE;
}

// ---------------------------------------------------------------------------
// RuntimeToken
// ---------------------------------------------------------------------------

export interface RuntimeToken {
  id: string;
  grantor: string;
  grantee: string;
  capabilities: string[];
  autonomy_level: AutonomyLevel;
  constraints: Record<string, unknown>;
  issued_at: number; // unix timestamp (seconds)
  expires_at: number; // unix timestamp (seconds), 0 = no expiry
  revoked: boolean;
}

/** True if the token has passed its expiry time. */
export function tokenExpired(token: RuntimeToken): boolean {
  if (token.expires_at <= 0) return false;
  return Date.now() / 1000 > token.expires_at;
}

/** True if the token is not revoked and not expired. */
export function tokenValid(token: RuntimeToken): boolean {
  return !token.revoked && !tokenExpired(token);
}

/** True if the token is valid and grants the given capability. */
export function tokenAllows(token: RuntimeToken, capability: string): boolean {
  if (!tokenValid(token)) return false;
  return token.capabilities.includes(capability) || token.capabilities.includes("*");
}

// ---------------------------------------------------------------------------
// CapabilityDelegation
// ---------------------------------------------------------------------------

export class CapabilityDelegation {
  private _tokens = new Map<string, RuntimeToken>();
  private _by_grantee = new Map<string, string[]>();

  /**
   * Grant capabilities from grantor to grantee.
   *
   * @param grantor      DID of the granting agent/human.
   * @param grantee      DID of the receiving agent.
   * @param capabilities List of capability names to delegate.
   * @param autonomy_level Maximum autonomy for these capabilities.
   * @param constraints  Additional scope constraints.
   * @param ttl_seconds  Time-to-live in seconds (0 = no expiry).
   * @returns The created RuntimeToken.
   */
  grant(
    grantor: string,
    grantee: string,
    capabilities: string[],
    autonomy_level: AutonomyLevel = AutonomyLevel.GUIDE,
    constraints: Record<string, unknown> = {},
    ttl_seconds = 0,
  ): RuntimeToken {
    const now = Date.now() / 1000;
    const token: RuntimeToken = {
      id: `rt-${randomBytes(8).toString("hex")}`,
      grantor,
      grantee,
      capabilities,
      autonomy_level,
      constraints,
      issued_at: now,
      expires_at: ttl_seconds > 0 ? now + ttl_seconds : 0,
      revoked: false,
    };
    this._tokens.set(token.id, token);
    if (!this._by_grantee.has(grantee)) {
      this._by_grantee.set(grantee, []);
    }
    this._by_grantee.get(grantee)!.push(token.id);
    return token;
  }

  /**
   * Revoke a grant. Returns true if found and revoked.
   */
  revoke(token_id: string): boolean {
    const token = this._tokens.get(token_id);
    if (token) {
      token.revoked = true;
      return true;
    }
    return false;
  }

  /**
   * Check if an agent is authorized for a capability.
   *
   * @param agent_did   The agent's DID.
   * @param capability  The capability to check.
   * @param min_autonomy Minimum required autonomy level.
   * @returns True if the agent has a valid token for this capability at or
   *          above the required autonomy level.
   */
  is_authorized(
    agent_did: string,
    capability: string,
    min_autonomy: AutonomyLevel = AutonomyLevel.DELEGATE,
  ): boolean {
    const min_idx = _AUTONOMY_ORDER.indexOf(min_autonomy);
    for (const tid of this._by_grantee.get(agent_did) ?? []) {
      const token = this._tokens.get(tid);
      if (!token || !tokenValid(token)) continue;
      if (!tokenAllows(token, capability)) continue;
      if (_AUTONOMY_ORDER.indexOf(token.autonomy_level) >= min_idx) return true;
    }
    return false;
  }

  /**
   * Get the highest autonomy level currently granted to an agent.
   */
  get_autonomy_level(agent_did: string): AutonomyLevel {
    let highest_idx = 0;
    let highest: AutonomyLevel = AutonomyLevel.WATCH;
    for (const tid of this._by_grantee.get(agent_did) ?? []) {
      const token = this._tokens.get(tid);
      if (!token || !tokenValid(token)) continue;
      const idx = _AUTONOMY_ORDER.indexOf(token.autonomy_level);
      if (idx > highest_idx) {
        highest_idx = idx;
        highest = token.autonomy_level;
      }
    }
    return highest;
  }

  /**
   * List grants, optionally filtered by grantee.
   */
  list_tokens(grantee?: string): RuntimeToken[] {
    if (grantee !== undefined) {
      return (this._by_grantee.get(grantee) ?? [])
        .map((tid) => this._tokens.get(tid))
        .filter((t): t is RuntimeToken => t !== undefined);
    }
    return Array.from(this._tokens.values());
  }

  /**
   * Remove expired and revoked tokens. Returns count removed.
   */
  cleanup_expired(): number {
    const to_remove: string[] = [];
    for (const [tid, t] of this._tokens.entries()) {
      if (!tokenValid(t)) to_remove.push(tid);
    }
    for (const tid of to_remove) {
      const token = this._tokens.get(tid)!;
      this._tokens.delete(tid);
      const grantee_list = this._by_grantee.get(token.grantee);
      if (grantee_list) {
        const pos = grantee_list.indexOf(tid);
        if (pos !== -1) grantee_list.splice(pos, 1);
      }
    }
    return to_remove.length;
  }
}
