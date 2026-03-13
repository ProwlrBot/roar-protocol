#!/usr/bin/env node
/**
 * ROAR Protocol — Golden fixture conformance validator (TypeScript/Node.js).
 *
 * Mirrors tests/validate_golden.py but uses Node.js 18+ built-ins only.
 * No npm install required.
 *
 * Run from the repo root:
 *   node tests/validate_golden.mjs
 */

import { createHmac } from "crypto";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GOLDEN = join(__dirname, "conformance", "golden");

const DID_PREFIX = "did:roar:";
const errors = [];
let passed = 0;

function check(name, condition, message) {
  if (condition) {
    passed++;
  } else {
    errors.push(`  ✗ ${name}: ${message}`);
  }
}

// ---------------------------------------------------------------------------
// pythonJsonDumps — replicates json.dumps(sort_keys=True)
// ---------------------------------------------------------------------------
function pythonJsonDumps(value) {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return "null";
    if (Number.isInteger(value)) return `${value}.0`;
    return String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return "[" + value.map(pythonJsonDumps).join(", ") + "]";
  }
  if (typeof value === "object" && value !== null) {
    const keys = Object.keys(value).sort();
    if (keys.length === 0) return "{}";
    const pairs = keys.map((k) => `${JSON.stringify(k)}: ${pythonJsonDumps(value[k])}`);
    return "{" + pairs.join(", ") + "}";
  }
  return String(value);
}

// ---------------------------------------------------------------------------
// identity.json
// ---------------------------------------------------------------------------
const rawIdentity = JSON.parse(readFileSync(join(GOLDEN, "identity.json"), "utf8"));

check("identity/parse", true, "");
check(
  "identity/did_prefix",
  rawIdentity.did.startsWith(DID_PREFIX),
  `DID must start with '${DID_PREFIX}', got '${rawIdentity.did}'`,
);
check(
  "identity/did_format",
  rawIdentity.did.includes(":agent:"),
  `Expected ':agent:' in DID, got '${rawIdentity.did}'`,
);
check(
  "identity/display_name",
  rawIdentity.display_name === "golden-agent",
  `Expected 'golden-agent', got '${rawIdentity.display_name}'`,
);
check(
  "identity/agent_type",
  rawIdentity.agent_type === "agent",
  `Expected 'agent', got '${rawIdentity.agent_type}'`,
);
check(
  "identity/capabilities",
  Array.isArray(rawIdentity.capabilities) && rawIdentity.capabilities.includes("python"),
  "Expected 'python' in capabilities",
);
check(
  "identity/version",
  rawIdentity.version === "1.0",
  `Expected '1.0', got '${rawIdentity.version}'`,
);
check(
  "identity/public_key_null",
  rawIdentity.public_key === null,
  "Expected public_key to be null",
);
// Round-trip field names
check("identity/roundtrip_did", "did" in rawIdentity, "Round-trip: 'did' field missing");
check(
  "identity/roundtrip_agent_type",
  rawIdentity.agent_type === "agent",
  "Round-trip: 'agent_type' field wrong",
);

console.log("identity.json    ", errors.some((e) => e.includes("identity")) ? "❌" : "✅");

// ---------------------------------------------------------------------------
// message.json
// ---------------------------------------------------------------------------
const rawMsg = JSON.parse(readFileSync(join(GOLDEN, "message.json"), "utf8"));

check("message/parse", true, "");
check(
  "message/roar_version",
  rawMsg.roar === "1.0",
  `Expected roar='1.0', got '${rawMsg.roar}'`,
);
check(
  "message/id_format",
  typeof rawMsg.id === "string" && rawMsg.id.startsWith("msg_"),
  `ID must start with 'msg_', got '${rawMsg.id}'`,
);
check(
  "message/intent_delegate",
  rawMsg.intent === "delegate",
  `Expected 'delegate', got '${rawMsg.intent}'`,
);
check(
  "message/from_did",
  rawMsg.from && rawMsg.from.did && rawMsg.from.did.startsWith(DID_PREFIX),
  `from.did must start with '${DID_PREFIX}'`,
);
check(
  "message/to_did",
  rawMsg.to && rawMsg.to.did && rawMsg.to.did.startsWith(DID_PREFIX),
  `to.did must start with '${DID_PREFIX}'`,
);
check(
  "message/payload_task",
  rawMsg.payload && "task" in rawMsg.payload,
  "Expected 'task' key in payload",
);
check(
  "message/context_session",
  rawMsg.context && rawMsg.context.session_id === "sess_golden",
  "Expected session_id='sess_golden' in context",
);
check(
  "message/auth_signature",
  rawMsg.auth && typeof rawMsg.auth.signature === "string" &&
    rawMsg.auth.signature.startsWith("hmac-sha256:"),
  "auth.signature must start with 'hmac-sha256:'",
);
check(
  "message/auth_timestamp",
  rawMsg.auth && rawMsg.auth.timestamp === 1710000000.0,
  `Expected auth.timestamp=1710000000.0, got ${rawMsg.auth?.timestamp}`,
);

// Verify HMAC signature
{
  const sigBody = pythonJsonDumps({
    id: rawMsg.id,
    from: rawMsg.from.did,
    to: rawMsg.to.did,
    intent: rawMsg.intent,
    payload: rawMsg.payload,
    context: rawMsg.context,
    timestamp: rawMsg.auth.timestamp,
  });
  const actualSig =
    "hmac-sha256:" +
    createHmac("sha256", "roar-conformance-test-secret").update(sigBody).digest("hex");
  check(
    "message/signature_valid",
    actualSig === rawMsg.auth.signature,
    `HMAC mismatch:\n    expected: ${rawMsg.auth.signature}\n    got:      ${actualSig}`,
  );
}

console.log("message.json     ", errors.some((e) => e.includes("message")) ? "❌" : "✅");

// ---------------------------------------------------------------------------
// stream-event.json
// ---------------------------------------------------------------------------
const rawEvent = JSON.parse(readFileSync(join(GOLDEN, "stream-event.json"), "utf8"));

check("stream/parse", true, "");
check(
  "stream/type",
  rawEvent.type === "task_update",
  `Expected 'task_update', got '${rawEvent.type}'`,
);
check(
  "stream/source_did",
  typeof rawEvent.source === "string" && rawEvent.source.startsWith(DID_PREFIX),
  `source must be a DID, got '${rawEvent.source}'`,
);
check(
  "stream/session_id",
  rawEvent.session_id === "sess_golden",
  `Expected 'sess_golden', got '${rawEvent.session_id}'`,
);
check(
  "stream/data_task_id",
  rawEvent.data && "task_id" in rawEvent.data,
  "Expected 'task_id' in data",
);
check(
  "stream/data_status",
  rawEvent.data && rawEvent.data.status === "completed",
  "Expected status='completed'",
);
check(
  "stream/timestamp",
  rawEvent.timestamp === 1710000000.0,
  `Expected timestamp=1710000000.0, got ${rawEvent.timestamp}`,
);

console.log(
  "stream-event.json",
  errors.some((e) => e.includes("stream")) ? "❌" : "✅",
);

// ---------------------------------------------------------------------------
// signature.json
// ---------------------------------------------------------------------------
const rawSig = JSON.parse(readFileSync(join(GOLDEN, "signature.json"), "utf8"));
const { inputs, secret, canonical_json, expected_signature } = rawSig;

const canonical = pythonJsonDumps(inputs);
const actualSig =
  "hmac-sha256:" + createHmac("sha256", secret).update(canonical).digest("hex");

check(
  "signature/canonical",
  canonical === canonical_json,
  `Canonical JSON mismatch:\n  expected: ${canonical_json}\n  got:      ${canonical}`,
);
check(
  "signature/hmac",
  actualSig === expected_signature,
  `HMAC mismatch:\n    expected: ${expected_signature}\n    got:      ${actualSig}`,
);

console.log("signature.json   ", errors.some((e) => e.includes("signature")) ? "❌" : "✅");

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------
const total = passed + errors.length;
console.log();
if (errors.length === 0) {
  console.log(`All ${total} conformance checks passed. ✅`);
} else {
  console.log(`${errors.length}/${total} checks failed:`);
  for (const e of errors) console.log(e);
  process.exit(1);
}
