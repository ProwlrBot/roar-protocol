/**
 * ROAR Protocol — canonical TypeScript type definitions.
 *
 * This file is the single source of truth for all wire format types in the TS SDK.
 * Field names and enum values must be identical to the Python SDK (roar_sdk/types.py).
 *
 * Layers:
 *   1 — Identity:   AgentIdentity, AgentCapability, AgentCard
 *   2 — Discovery:  DiscoveryEntry, AgentDirectory
 *   3 — Connect:    TransportType, ConnectionConfig
 *   4 — Exchange:   MessageIntent, ROARMessage
 *   5 — Stream:     StreamEventType, StreamEvent
 */

import { randomBytes } from "crypto";

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
// Layer 3: Connect
// ---------------------------------------------------------------------------

export const TransportType = {
  STDIO: "stdio",
  HTTP: "http",
  WEBSOCKET: "websocket",
  GRPC: "grpc",
} as const;

export type TransportType = (typeof TransportType)[keyof typeof TransportType];

export interface ConnectionConfig {
  transport: TransportType;
  url: string;
  auth_method: string; // "hmac" | "jwt" | "mtls" | "none"
  secret: string;
  timeout_ms: number;
}

export function defaultConnectionConfig(
  overrides: Partial<ConnectionConfig> = {},
): ConnectionConfig {
  return {
    transport: TransportType.HTTP,
    url: "",
    auth_method: "hmac",
    secret: "",
    timeout_ms: 30000,
    ...overrides,
  };
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
 *
 * Use fromWire() to parse, toWire() to serialize.
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

/** Parse a raw wire JSON object into a ROARMessage. Wire uses "from"/"to". */
export function messageFromWire(raw: Record<string, unknown>): ROARMessage {
  return {
    roar: (raw["roar"] as string) ?? "1.0",
    id: raw["id"] as string,
    from_identity: raw["from"] as AgentIdentity,
    to_identity: raw["to"] as AgentIdentity,
    intent: raw["intent"] as MessageIntent,
    payload: (raw["payload"] as Record<string, unknown>) ?? {},
    context: (raw["context"] as Record<string, unknown>) ?? {},
    auth: (raw["auth"] as Record<string, unknown>) ?? {},
    timestamp: raw["timestamp"] as number,
  };
}

/** Serialize a ROARMessage to wire format JSON object ("from"/"to" keys). */
export function messageToWire(msg: ROARMessage): Record<string, unknown> {
  return {
    roar: msg.roar,
    id: msg.id,
    from: msg.from_identity,
    to: msg.to_identity,
    intent: msg.intent,
    payload: msg.payload,
    context: msg.context,
    auth: msg.auth,
    timestamp: msg.timestamp,
  };
}

// ---------------------------------------------------------------------------
// Layer 5: Stream
// ---------------------------------------------------------------------------

/** Must match Python's StreamEventType enum values exactly. */
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

/** Generate a hex string of n bytes. */
export function randomHex(bytes: number): string {
  return randomBytes(bytes).toString("hex");
}
