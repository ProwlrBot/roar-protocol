#!/usr/bin/env npx tsx
/**
 * Quickstart 02: Register agents, discover by capability, send a message.
 *
 * Run: npx tsx 02_discover_and_talk.ts
 */
import {
  createIdentity,
  createMessage,
  signMessage,
  verifyMessage,
  AgentDirectory,
  MessageIntent,
} from "@roar-protocol/sdk";

// Create two agents (Layer 1)
const coder = createIdentity("coder", { capabilities: ["code-review", "python"] });
const reviewer = createIdentity("reviewer", { capabilities: ["code-review"] });

// Register in a directory (Layer 2)
const directory = new AgentDirectory();
directory.register({
  identity: coder,
  description: "Writes Python code",
  skills: ["python"],
  channels: ["http"],
  endpoints: [],
  declared_capabilities: [],
});
directory.register({
  identity: reviewer,
  description: "Reviews code",
  skills: ["review"],
  channels: ["http"],
  endpoints: [],
  declared_capabilities: [],
});

// Discover agents with "code-review" capability
const results = directory.search("code-review");
console.log(`Found ${results.length} agents with 'code-review':`);
for (const entry of results) {
  console.log(`  - ${entry.agent_card.identity.display_name} (${entry.agent_card.identity.did})`);
}

// Send a signed message (Layer 4)
const secret = process.env.ROAR_SIGNING_SECRET || "quickstart-demo-key";
const msg = signMessage(
  createMessage(coder, reviewer, MessageIntent.DELEGATE, {
    task: "review",
    file: "main.py",
    lines: "42-58",
  }),
  secret,
);

console.log(`\nSigned message ID: ${msg.id}`);
console.log(`Signature: ${msg.auth.signature?.substring(0, 40)}...`);

// Verify
const valid = verifyMessage(msg, secret);
console.log(`Signature verified: ${valid}`);
