import test from "node:test";
import assert from "node:assert/strict";

import { ChallengeStore } from "../src/hub_auth.js";

test("ChallengeStore issues + consumes once (replay-safe)", () => {
  const store = new ChallengeStore();
  const ch = store.issue("did:key:abc", "11".repeat(32), { ok: true });
  assert.equal(typeof ch.challenge_id, "string");
  assert.equal(typeof ch.nonce, "string");

  const first = store.consume(ch.challenge_id);
  assert.ok(first);

  const second = store.consume(ch.challenge_id);
  assert.equal(second, null);
});
