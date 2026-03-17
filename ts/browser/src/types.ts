/**
 * ROAR Protocol — Browser SDK type definitions.
 *
 * Mirrors the Node SDK types (roar_sdk/types.ts) without any Node.js dependencies.
 * All types are wire-compatible with the Node and Python SDKs.
 */

// ---------------------------------------------------------------------------
// Layer 1: Identity
// ---------------------------------------------------------------------------

export interface AgentIdentity {
  did: string;
  display_name: string;
  agent_type: string; // "agent" | "tool" | "human" | "ide"
  capabilities: string[];
  version: string;
  public_key: string | null;
}

export interface AgentCapability {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
}

export interface AgentCard {
  identity: AgentIdentity;
  description: string;
  skills: string[];
  channels: string[];
  endpoints: Record<string, string>;
  declared_capabilities: AgentCapability[];
  metadata: Record<string, unknown>;
  attestation?: string; // base64url Ed25519 signature over canonical card JSON
}

// ---------------------------------------------------------------------------
// Layer 2: Discovery
// ---------------------------------------------------------------------------

export interface DiscoveryEntry {
  agent_card: AgentCard;
  registered_at: number; // unix timestamp
  last_seen: number;
  hub_url: string;
}

export class AgentDirectory {
  private _agents = new Map<string, DiscoveryEntry>();

  register(card: AgentCard): DiscoveryEntry {
    const entry: DiscoveryEntry = {
      agent_card: card,
      registered_at: Date.now() / 1000,
      last_seen: Date.now() / 1000,
      hub_url: "",
    };
    this._agents.set(card.identity.did, entry);
    return entry;
  }

  unregister(did: string): boolean {
    return this._agents.delete(did);
  }

  lookup(did: string): DiscoveryEntry | undefined {
    return this._agents.get(did);
  }

  search(capability: string): DiscoveryEntry[] {
    return Array.from(this._agents.values()).filter((e) =>
      e.agent_card.identity.capabilities.includes(capability),
    );
  }

  listAll(): DiscoveryEntry[] {
    return Array.from(this._agents.values());
  }
}

// ---------------------------------------------------------------------------
// Layer 4: Exchange
// ---------------------------------------------------------------------------

/** Must match Python's MessageIntent enum values exactly. */
export const MessageIntent = {
  EXECUTE: "execute",
  DELEGATE: "delegate",
  UPDATE: "update",
  ASK: "ask",
  RESPOND: "respond",
  NOTIFY: "notify",
  DISCOVER: "discover",
} as const;

export type MessageIntent = (typeof MessageIntent)[keyof typeof MessageIntent];

/**
 * ROAR wire message. Internal fields use _identity suffix; JSON wire format
 * uses "from" and "to" as keys (matching the Python alias).
 */
export interface ROARMessage {
  roar: string;
  id: string;
  from_identity: AgentIdentity; // serializes as "from"
  to_identity: AgentIdentity;   // serializes as "to"
  intent: MessageIntent;
  payload: Record<string, unknown>;
  context: Record<string, unknown>;
  auth: Record<string, unknown>;
  timestamp: number; // unix timestamp (float)
}

// ---------------------------------------------------------------------------
// Layer 5: Stream
// ---------------------------------------------------------------------------

export const StreamEventType = {
  TOOL_CALL: "tool_call",
  MCP_REQUEST: "mcp_request",
  REASONING: "reasoning",
  TASK_UPDATE: "task_update",
  MONITOR_ALERT: "monitor_alert",
  AGENT_STATUS: "agent_status",
  CHECKPOINT: "checkpoint",
  WORLD_UPDATE: "world_update",
} as const;

export type StreamEventType =
  (typeof StreamEventType)[keyof typeof StreamEventType];

export interface StreamEvent {
  type: StreamEventType;
  source: string;
  session_id: string;
  data: Record<string, unknown>;
  timestamp: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Generate a hex string of n random bytes.
 * Uses globalThis.crypto.getRandomValues — works in all modern browsers.
 */
export function randomHex(bytes: number): string {
  const buf = new Uint8Array(bytes);
  globalThis.crypto.getRandomValues(buf);
  return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Create an AgentIdentity with auto-generated DID.
 * Uses crypto.randomUUID() which is available in all modern browsers.
 */
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
