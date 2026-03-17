#!/usr/bin/env npx tsx
/**
 * Quickstart 01: Create an agent identity and handle messages.
 *
 * Run: npx tsx 01_hello_agent.ts
 */
import {
  createIdentity,
  createMessage,
  signMessage,
  verifyMessage,
  MessageIntent,
  ROARMessage,
} from "@roar-protocol/sdk";
import * as http from "node:http";

const PORT = 8089;
const SECRET = "quickstart-secret";

// Create an agent identity (Layer 1)
const identity = createIdentity("hello-agent", {
  agentType: "agent",
  capabilities: ["greeting"],
});
console.log("Agent DID:", identity.did);

// Handle incoming messages (Layer 4)
async function handleMessage(incoming: ROARMessage): Promise<ROARMessage> {
  console.log(`Received from ${incoming.from_identity.display_name}:`, incoming.payload);
  return signMessage(
    createMessage(
      identity,
      incoming.from_identity,
      MessageIntent.RESPOND,
      { greeting: "Hello from ROAR!", received: incoming.payload },
      { in_reply_to: incoming.id },
    ),
    SECRET,
  );
}

// Start HTTP server (Layer 3)
const server = http.createServer(async (req, res) => {
  if (req.method === "GET" && req.url === "/roar/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", protocol: "roar/1.0" }));
    return;
  }
  if (req.method !== "POST" || req.url !== "/roar/message") {
    res.writeHead(404).end();
    return;
  }
  let body = "";
  req.on("data", (c) => (body += c));
  req.on("end", async () => {
    const msg = JSON.parse(body) as ROARMessage;
    if (!verifyMessage(msg, SECRET)) {
      res.writeHead(403).end(JSON.stringify({ error: "invalid_signature" }));
      return;
    }
    const response = await handleMessage(msg);
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(response));
  });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`\nStarting on http://127.0.0.1:${PORT}`);
  console.log("  POST /roar/message  — send a message");
  console.log("  GET  /roar/health   — health check");
});
