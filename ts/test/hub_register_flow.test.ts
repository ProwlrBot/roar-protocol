import test from "node:test";
import assert from "node:assert/strict";

import { ROARHub } from "../src/hub.js";
import { generateEd25519KeyPair } from "../src/signing.js";

async function httpJson(method: string, url: string, body?: any): Promise<any> {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const json = await res.json();
  return { status: res.status, json };
}

test("ROARHub register challenge flow accepts valid proof-of-possession", async () => {
  const hub = new ROARHub({ host: "127.0.0.1", port: 0 });
  await hub.serve();

  const addr = (hub as any)._httpServer.address();
  const base = `http://127.0.0.1:${addr.port}`;

  const kp = generateEd25519KeyPair();
  const did = "did:key:test";

  const card = {
    identity: { did, public_key: kp.publicKeyHex, capabilities: [] },
    description: "",
    skills: [],
    channels: [],
    endpoints: { http: "" },
    declared_capabilities: [],
    metadata: {},
  };

  const step1 = await httpJson("POST", `${base}/roar/agents/register`, {
    did,
    public_key: kp.publicKeyHex,
    card,
  });
  assert.equal(step1.status, 200);
  assert.ok(step1.json.challenge_id);
  assert.ok(step1.json.nonce);

  // Sign nonce with ed25519 private key.
  // Use crypto directly to avoid changing signing-body semantics.
  const { createPrivateKey, createPublicKey, sign } = await import("node:crypto");
  const raw = Buffer.from(kp.privateKeyHex, "hex");
  const pkcs8Header = Buffer.from("302e020100300506032b657004220420", "hex");
  const der = Buffer.concat([pkcs8Header, raw]);
  const priv = createPrivateKey({ key: der, format: "der", type: "pkcs8" });
  const sig = sign(null, Buffer.from(step1.json.nonce, "utf8"), priv).toString("base64url");

  const step2 = await httpJson("POST", `${base}/roar/agents/challenge`, {
    challenge_id: step1.json.challenge_id,
    signature: `ed25519:${sig}`,
  });

  assert.equal(step2.status, 200);
  assert.equal(step2.json.registered, true);

  const list = await httpJson("GET", `${base}/roar/agents`);
  assert.equal(list.status, 200);
  assert.equal(list.json.agents.length, 1);

  await hub.stop();
});
