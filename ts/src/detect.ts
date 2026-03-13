/**
 * ROAR Protocol — Protocol auto-detection adapter (Layer 4).
 *
 * Examines the structure of an incoming JSON message to determine whether
 * it is ROAR native, MCP (JSON-RPC 2.0), A2A (Google A2A), or ACP protocol
 * format, then provides a best-effort normalisation to ROARMessage.
 *
 * Detection priority:
 *   1. ROAR   — has "roar" version field and "intent" field
 *   2. A2A    — has "role" field whose value is "user" | "assistant" | "system"
 *   3. ACP    — JSON-RPC 2.0 with method starting with "session/" | "initialize" | "shutdown"
 *   4. MCP    — JSON-RPC 2.0 with "method" field (generic)
 *   5. UNKNOWN
 *
 * Note: ACP is checked before generic MCP because ACP is a JSON-RPC 2.0 subset.
 */

import { randomHex } from "./types.js";
import type { ROARMessage, AgentIdentity } from "./types.js";
import { MessageIntent } from "./types.js";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type DetectedProtocol = "roar" | "mcp" | "a2a" | "acp" | "unknown";

// ---------------------------------------------------------------------------
// Internal constants
// ---------------------------------------------------------------------------

const VALID_INTENTS = new Set<string>(Object.values(MessageIntent));

const A2A_ROLES = new Set(["user", "assistant", "system"]);

const ACP_METHOD_PREFIXES = ["session/", "initialize", "shutdown"];

// ---------------------------------------------------------------------------
// detectProtocol
// ---------------------------------------------------------------------------

/**
 * Detect the protocol of an incoming raw message object.
 *
 * @param raw - The parsed JSON message as a plain object.
 * @returns The detected protocol identifier.
 */
export function detectProtocol(raw: Record<string, unknown>): DetectedProtocol {
  // 1. ROAR: has "roar" version field and valid "intent" field
  if ("roar" in raw && typeof raw["intent"] === "string" && VALID_INTENTS.has(raw["intent"])) {
    return "roar";
  }

  // 2. A2A: has "role" field with a Google A2A role value
  if (typeof raw["role"] === "string" && A2A_ROLES.has(raw["role"])) {
    return "a2a";
  }

  // 3. JSON-RPC 2.0 based protocols
  if (raw["jsonrpc"] === "2.0" && typeof raw["method"] === "string") {
    const method = raw["method"] as string;

    // ACP must be checked before generic MCP (ACP is a JSON-RPC 2.0 subset)
    if (ACP_METHOD_PREFIXES.some((prefix) => method.startsWith(prefix))) {
      return "acp";
    }

    // Generic MCP
    return "mcp";
  }

  return "unknown";
}

// ---------------------------------------------------------------------------
// normalizeToROAR
// ---------------------------------------------------------------------------

/** Build a minimal anonymous AgentIdentity placeholder. */
function anonymousIdentity(displayName: string): AgentIdentity {
  return {
    did: `did:roar:agent:${displayName}-${randomHex(8)}`,
    display_name: displayName,
    agent_type: "agent",
    capabilities: [],
    version: "1.0",
    public_key: null,
  };
}

/**
 * Convert a detected foreign-protocol message to a ROARMessage on a
 * best-effort basis. Returns null for ROAR messages (already native)
 * and for unknown messages that cannot be mapped.
 *
 * @param raw - The parsed JSON message as a plain object.
 * @returns A ROARMessage, or null if the message cannot be normalised.
 */
export function normalizeToROAR(raw: Record<string, unknown>): ROARMessage | null {
  const protocol = detectProtocol(raw);

  switch (protocol) {
    case "roar":
      // Already ROAR — callers should use messageFromWire() directly.
      return null;

    case "mcp": {
      // MCP tool-call request: { jsonrpc, id, method, params }
      const toolName = (raw["method"] as string) ?? "unknown";
      const params = (raw["params"] as Record<string, unknown>) ?? {};
      return {
        roar: "1.0",
        id: `msg_${randomHex(5)}`,
        from_identity: anonymousIdentity("mcp-caller"),
        to_identity: anonymousIdentity(toolName),
        intent: MessageIntent.EXECUTE,
        payload: { action: toolName, params },
        context: { protocol: "mcp", jsonrpc_id: raw["id"] ?? null },
        auth: {},
        timestamp: Date.now() / 1000,
      };
    }

    case "a2a": {
      // A2A chat message: { role, content, ... }
      const role = (raw["role"] as string) ?? "user";
      const content = raw["content"] ?? "";
      const intent = role === "user" ? MessageIntent.ASK : MessageIntent.RESPOND;
      return {
        roar: "1.0",
        id: `msg_${randomHex(5)}`,
        from_identity: anonymousIdentity(`a2a-${role}`),
        to_identity: anonymousIdentity("a2a-agent"),
        intent,
        payload: { content },
        context: { protocol: "a2a", role },
        auth: {},
        timestamp: Date.now() / 1000,
      };
    }

    case "acp": {
      // ACP JSON-RPC 2.0 method call: session/ or initialize / shutdown
      const method = (raw["method"] as string) ?? "";
      const params = (raw["params"] as Record<string, unknown>) ?? {};
      const isSessionEnd =
        method === "shutdown" || method === "session/end" || method === "session/delete";
      const intent = isSessionEnd ? MessageIntent.NOTIFY : MessageIntent.ASK;
      return {
        roar: "1.0",
        id: `msg_${randomHex(5)}`,
        from_identity: anonymousIdentity("acp-ide"),
        to_identity: anonymousIdentity("acp-agent"),
        intent,
        payload: { method, params },
        context: { protocol: "acp", jsonrpc_id: raw["id"] ?? null },
        auth: {},
        timestamp: Date.now() / 1000,
      };
    }

    default:
      return null;
  }
}
