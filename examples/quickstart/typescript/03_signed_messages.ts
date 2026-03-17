#!/usr/bin/env npx tsx
/**
 * Quickstart 03: HMAC-SHA256 and Ed25519 signing with tamper detection.
 *
 * Run: npx tsx 03_signed_messages.ts
 */
import {
  createIdentity,
  createMessage,
  signMessage,
  verifyMessage,
  generateEd25519KeyPair,
  signEd25519,
  verifyEd25519,
  MessageIntent,
} from "@roar-protocol/sdk";

// --- HMAC-SHA256 signing (symmetric, shared secret) ---
const alice = createIdentity("alice", { capabilities: ["crypto"] });
const bob = createIdentity("bob", { capabilities: ["crypto"] });
const secret = process.env.ROAR_SIGNING_SECRET || "quickstart-demo-key";

const msg = signMessage(
  createMessage(alice, bob, MessageIntent.NOTIFY, {
    text: "Hello Bob, this message is tamper-proof!",
  }),
  secret,
);

console.log(`HMAC signature: ${msg.auth.signature?.substring(0, 50)}...`);
console.log(`HMAC-SHA256: verified = ${verifyMessage(msg, secret)}`);

// Tamper detection
msg.payload.text = "TAMPERED!";
console.log(`HMAC-SHA256: tamper detected = ${!verifyMessage(msg, secret)}`);

// --- Ed25519 signing (asymmetric, key pair) ---
const keyPair = generateEd25519KeyPair();
console.log(`\nEd25519 public key: ${keyPair.publicKey.substring(0, 32)}...`);

const agent = createIdentity("ed25519-agent", { publicKey: keyPair.publicKey });
const peer = createIdentity("peer");

const msg2 = createMessage(agent, peer, MessageIntent.DELEGATE, {
  task: "verify-me",
});
const signed = signEd25519(msg2, keyPair.privateKey);
console.log(`Ed25519 signature: ${signed.auth.signature?.substring(0, 50)}...`);
console.log(`Ed25519: verified = ${verifyEd25519(signed)}`);

console.log("\nAll signing demos passed!");
