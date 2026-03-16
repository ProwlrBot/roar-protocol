#!/usr/bin/env node
/**
 * Cross-SDK verification helper for ROAR Protocol interop tests.
 *
 * Usage:
 *   node tests/verify_cross_sdk.mjs <message-json-path> <hmac-secret>
 *
 * Reads a ROARMessage JSON file, verifies its HMAC-SHA256 signature using the
 * TypeScript SDK compiled output (ts/dist/), and exits 0 on success or 1 on failure.
 *
 * Requires: npm run build in ts/ before running.
 */

import { readFileSync } from "fs";
import { messageFromWire } from "../ts/dist/types.js";
import { verifyMessage } from "../ts/dist/message.js";

const [, , msgPath, secret] = process.argv;

if (!msgPath || !secret) {
  console.error("Usage: verify_cross_sdk.mjs <message-json-path> <hmac-secret>");
  process.exit(2);
}

let wire;
try {
  wire = JSON.parse(readFileSync(msgPath, "utf8"));
} catch (err) {
  console.error(`Failed to read/parse message file: ${err.message}`);
  process.exit(1);
}

let msg;
try {
  msg = messageFromWire(wire);
} catch (err) {
  console.error(`Failed to parse ROAR message from wire format: ${err.message}`);
  process.exit(1);
}

// maxAgeSeconds=0 disables the replay-window check, matching Python's
// max_age_seconds=0 used in validate_golden.py for static fixture verification.
const ok = verifyMessage(msg, secret, 0);

if (ok) {
  console.log("ROAR cross-SDK verify: OK");
  process.exit(0);
} else {
  console.error("ROAR cross-SDK verify: FAILED — signature mismatch or stale timestamp");
  process.exit(1);
}
