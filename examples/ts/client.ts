#!/usr/bin/env node
/**
 * ROAR Protocol — Client Example (TypeScript/Node.js)
 *
 * Sends a DELEGATE message to the echo server and prints the response.
 * Demonstrates ROARClient usage for Layer 1-4.
 *
 * Requirements: Start echo_server.ts first.
 *
 * Usage (Bun):
 *   bun run examples/ts/client.ts
 *
 * Usage (ts-node):
 *   npx ts-node examples/ts/client.ts
 */

import * as https from "https";
import * as http from "http";
import {
  MessageIntent,
  ROARMessage,
  createIdentity,
  createMessage,
  signMessage,
  verifyMessage,
  messageToWire,
  messageFromWire,
} from "@roar-protocol/sdk";

const SERVER_URL = "http://127.0.0.1:8089/roar/message";
const SHARED_SECRET = process.env.ROAR_SIGNING_SECRET || "";

// ── Step 1: Create a client identity ────────────────────────────────────────
const clientIdentity = createIdentity("ts-client", {
  agentType: "agent",
  capabilities: ["code"],
});
console.log("Client DID:", clientIdentity.did);

// ── Step 2: Create a placeholder server identity ─────────────────────────────
// In production, discover the real identity from /roar/agents or a directory.
const serverIdentity = createIdentity("echo-server", { agentType: "agent" });

// ── Step 3: Create and sign a DELEGATE message ───────────────────────────────
const msg = signMessage(
  createMessage(
    clientIdentity,
    serverIdentity,
    MessageIntent.DELEGATE,
    { task: "reflect this payload back to me", priority: "low" },
    { session_id: "ts-example-session" },
  ),
  SHARED_SECRET,
);

console.log("\n→ Sending DELEGATE message:");
console.log("  id:     ", msg.id);
console.log("  intent: ", msg.intent);
console.log("  payload:", msg.payload);
console.log("  signed: ", typeof msg.auth.signature === "string");

// ── Step 4: Send over HTTP ───────────────────────────────────────────────────
function postJson(url: string, body: unknown): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const json = JSON.stringify(body);
    const parsed = new URL(url);
    const lib = parsed.protocol === "https:" ? https : http;

    const req = lib.request(
      {
        hostname: parsed.hostname,
        port: parsed.port,
        path: parsed.pathname,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(json),
        },
      },
      (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`HTTP ${res.statusCode}: ${data}`));
          } else {
            resolve(JSON.parse(data));
          }
        });
      },
    );

    req.on("error", reject);
    req.write(json);
    req.end();
  });
}

(async () => {
  try {
    const response = messageFromWire((await postJson(SERVER_URL, messageToWire(msg))) as Record<string, unknown>);

    console.log("\n← Response received:");
    console.log("  intent: ", response.intent);
    console.log("  payload:", response.payload);

    // Verify the response signature (if the server signed it)
    if (response.auth?.signature) {
      const valid = verifyMessage(response, SHARED_SECRET);
      console.log("  sig ok: ", valid);
    }

    console.log("\nROAR round-trip complete.");
  } catch (err) {
    console.error("Error:", err);
    console.error(
      "\nMake sure echo_server.ts is running: npx ts-node examples/ts/echo_server.ts",
    );
    process.exit(1);
  }
})();
