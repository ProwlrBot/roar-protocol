#!/usr/bin/env node
/**
 * ROAR Protocol — Echo Server (TypeScript/Node.js)
 *
 * Minimal HTTP server that accepts DELEGATE messages and echoes them back.
 * Demonstrates Layer 1 (identity), Layer 4 (exchange), and signing.
 *
 * Run this first, then run client.ts in a second terminal.
 *
 * Requirements:
 *   cd prowlrbot/packages/roar-sdk-ts && npm ci && npm run build
 *   # or use ts-node / Bun directly
 *
 * Usage (compiled):
 *   node dist/examples/ts/echo_server.js
 *
 * Usage (Bun):
 *   bun run examples/ts/echo_server.ts
 *
 * Usage (ts-node):
 *   npx ts-node examples/ts/echo_server.ts
 */

import * as http from "http";
import {
  MessageIntent,
  ROARMessage,
  createIdentity,
  createMessage,
  signMessage,
  verifyMessage,
} from "../../ts/src/index.js";

const PORT = 8089;
const SHARED_SECRET = "roar-example-shared-secret";

// ── Step 1: Give this server an identity ────────────────────────────────────
const identity = createIdentity("echo-server", {
  agentType: "agent",
  capabilities: ["echo", "reflect"],
});
console.log("Server DID:", identity.did);

// ── Step 2: Intent dispatch map ──────────────────────────────────────────────
async function handleMessage(incoming: ROARMessage): Promise<ROARMessage> {
  if (incoming.intent !== MessageIntent.DELEGATE) {
    return signMessage(
      createMessage(
        identity,
        incoming.from_identity,
        MessageIntent.RESPOND,
        {
          error: "unhandled_intent",
          message: `No handler for intent '${incoming.intent}'`,
        },
        { in_reply_to: incoming.id },
      ),
      SHARED_SECRET,
    );
  }

  console.log(
    `← DELEGATE from ${incoming.from_identity.display_name}:`,
    incoming.payload,
  );

  const response = signMessage(
    createMessage(
      identity,
      incoming.from_identity,
      MessageIntent.RESPOND,
      { echo: incoming.payload, status: "ok" },
      { in_reply_to: incoming.id },
    ),
    SHARED_SECRET,
  );

  console.log("→ RESPOND:", response.payload);
  return response;
}

// ── Step 3: Start the HTTP server ───────────────────────────────────────────
const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/roar/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", protocol: "roar/1.0" }));
    return;
  }

  if (req.method !== "POST" || req.url !== "/roar/message") {
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not_found" }));
    return;
  }

  let body = "";
  req.on("data", (chunk) => (body += chunk));
  req.on("end", async () => {
    try {
      const data = JSON.parse(body) as ROARMessage;

      // Verify signature
      if (!verifyMessage(data, SHARED_SECRET)) {
        res.writeHead(403, { "Content-Type": "application/json" });
        res.end(
          JSON.stringify({
            error: "signature_invalid",
            detail: "HMAC signature verification failed.",
          }),
        );
        return;
      }

      const response = await handleMessage(data);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(response));
    } catch (err) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({ error: "invalid_message", detail: String(err) }),
      );
    }
  });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`\nROAR echo server listening on http://127.0.0.1:${PORT}`);
  console.log("Endpoints:");
  console.log("  POST /roar/message  — receive a ROARMessage");
  console.log("  GET  /roar/health   — health check");
  console.log("\nNow run: npx ts-node examples/ts/client.ts");
});
