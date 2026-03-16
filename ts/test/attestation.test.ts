/**
 * Tests for AgentCard signed attestation (discovery poisoning mitigation).
 */

import test from "node:test";
import assert from "node:assert/strict";

import { generateEd25519KeyPair, signAgentCard, verifyAgentCard } from "../src/signing.js";
import type { AgentCard } from "../src/types.js";

function makeCard(withPublicKey = true): { card: AgentCard; privateKeyHex: string } {
  const { privateKeyHex, publicKeyHex } = generateEd25519KeyPair();
  const card: AgentCard = {
    identity: {
      did: "did:roar:agent:test-agent-aabbccdd",
      display_name: "test-agent",
      agent_type: "agent",
      capabilities: ["read", "write"],
      version: "1.0",
      public_key: withPublicKey ? publicKeyHex : null,
    },
    description: "A test agent",
    skills: ["testing"],
    channels: ["http"],
    endpoints: { main: "https://example.com/roar" },
    declared_capabilities: [
      { name: "read", description: "Read capability", input_schema: {}, output_schema: {} },
    ],
    metadata: {},
  };
  return { card, privateKeyHex };
}

// ---------------------------------------------------------------------------
// 1. Signing sets attestation and verification passes
// ---------------------------------------------------------------------------

test("signAgentCard sets attestation and verifyAgentCard returns true", () => {
  const { card, privateKeyHex } = makeCard();
  assert.equal(card.attestation, undefined, "attestation should be undefined before signing");
  const result = signAgentCard(card, privateKeyHex);
  assert.equal(typeof result, "string");
  assert.ok(result.length > 0);
  assert.equal(card.attestation, result);
  assert.equal(verifyAgentCard(card), true);
});

// ---------------------------------------------------------------------------
// 2. Tampered card fails verification
// ---------------------------------------------------------------------------

test("tampered description fails verifyAgentCard", () => {
  const { card, privateKeyHex } = makeCard();
  signAgentCard(card, privateKeyHex);
  card.description = "TAMPERED description";
  assert.equal(verifyAgentCard(card), false);
});

test("tampered skills fails verifyAgentCard", () => {
  const { card, privateKeyHex } = makeCard();
  signAgentCard(card, privateKeyHex);
  card.skills = ["hacked"];
  assert.equal(verifyAgentCard(card), false);
});

test("tampered capabilities fails verifyAgentCard", () => {
  const { card, privateKeyHex } = makeCard();
  signAgentCard(card, privateKeyHex);
  card.identity = { ...card.identity, capabilities: ["admin"] };
  assert.equal(verifyAgentCard(card), false);
});

// ---------------------------------------------------------------------------
// 3. Missing attestation returns false
// ---------------------------------------------------------------------------

test("missing attestation returns false", () => {
  const { card } = makeCard();
  assert.equal(verifyAgentCard(card), false);
});

test("empty string attestation returns false", () => {
  const { card } = makeCard();
  card.attestation = "";
  assert.equal(verifyAgentCard(card), false);
});

// ---------------------------------------------------------------------------
// 4. Missing public_key returns false
// ---------------------------------------------------------------------------

test("missing public_key returns false even with attestation set", () => {
  const { card, privateKeyHex } = makeCard(false);
  signAgentCard(card, privateKeyHex);
  // attestation was set but public_key is null
  assert.equal(verifyAgentCard(card), false);
});

// ---------------------------------------------------------------------------
// 5. attestation field is optional / backwards compatible
// ---------------------------------------------------------------------------

test("AgentCard without attestation is valid (backwards compatible)", () => {
  const { card } = makeCard();
  assert.equal(card.attestation, undefined);
  // Should not throw and verification should simply return false
  assert.equal(verifyAgentCard(card), false);
});
