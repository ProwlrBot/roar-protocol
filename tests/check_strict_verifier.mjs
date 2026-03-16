#!/usr/bin/env node
/**
 * Security invariants for StrictMessageVerifier — TypeScript SDK.
 * Mirrors tests/check_strict_verifier.py exactly.
 */

import { createIdentity, createMessage, signMessage } from "../ts/dist/message.js";
import { MessageIntent } from "../ts/dist/types.js";
import { IdempotencyGuard } from "../ts/dist/dedup.js";
import { StrictMessageVerifier } from "../ts/dist/verifier.js";

const SRC = createIdentity("sender");
const DST = createIdentity("receiver");

function makeSignedMsg(secret = "test-secret") {
  const msg = createMessage(SRC, DST, MessageIntent.DELEGATE, { task: "hello" });
  signMessage(msg, secret);
  return msg;
}

function assertOk(cond, name) {
  if (!cond) throw new Error(`FAIL: ${name}`);
}

// 1. Valid message passes
const msg1 = makeSignedMsg();
const replayVerifier = new StrictMessageVerifier({
  hmacSecret: "test-secret",
  expectedRecipientDid: DST.did,
  replayGuard: new IdempotencyGuard(),
});
assertOk(replayVerifier.verify(msg1).ok, "valid_message");

// 2. Replay rejected
assertOk(!replayVerifier.verify(msg1).ok, "replay_rejected");
assertOk(replayVerifier.verify(msg1).error === "replay_detected", "replay_error_code");

// 3. Recipient binding enforced
// Capture DST.did BEFORE mutating to_identity (createMessage stores by reference)
const dstDid = DST.did;
const msg2 = makeSignedMsg();
msg2.to_identity = { ...msg2.to_identity, did: "did:roar:agent:not-me-00000000" };
const verifier2 = new StrictMessageVerifier({ hmacSecret: "test-secret", expectedRecipientDid: dstDid });
assertOk(verifier2.verify(msg2).error === "recipient_mismatch", "recipient_binding");

// 4. Future timestamp rejected
const msg3 = makeSignedMsg();
msg3.auth["timestamp"] = Date.now() / 1000 + 120;
const verifier3 = new StrictMessageVerifier({ hmacSecret: "test-secret", expectedRecipientDid: DST.did });
assertOk(verifier3.verify(msg3).error === "message_from_future", "future_timestamp_rejected");

// 5. Tampered signature rejected
const msg4 = makeSignedMsg();
msg4.auth["signature"] = "hmac-sha256:" + "0".repeat(64);
const verifier4 = new StrictMessageVerifier({ hmacSecret: "test-secret", expectedRecipientDid: DST.did });
assertOk(verifier4.verify(msg4).error === "invalid_hmac_signature", "tamper_detected");

// 6. Disallowed scheme rejected
const msg5 = makeSignedMsg();
msg5.auth["signature"] = "rsa-pkcs1:abc";
const verifier5 = new StrictMessageVerifier({ hmacSecret: "test-secret", allowedSignatureSchemes: ["hmac-sha256"] });
assertOk(verifier5.verify(msg5).error === "signature_scheme_not_allowed", "scheme_not_allowed");

// 7. Missing signature rejected
const msg6 = makeSignedMsg();
delete msg6.auth["signature"];
const verifier6 = new StrictMessageVerifier({ hmacSecret: "test-secret" });
assertOk(verifier6.verify(msg6).error === "missing_or_invalid_signature", "missing_signature");

// 8. Expired message rejected
const msg7 = makeSignedMsg();
msg7.auth["timestamp"] = Date.now() / 1000 - 400;
const verifier7 = new StrictMessageVerifier({ hmacSecret: "test-secret" });
assertOk(verifier7.verify(msg7).error === "message_expired", "expired_message");

console.log("strict verifier checks passed ✅");
