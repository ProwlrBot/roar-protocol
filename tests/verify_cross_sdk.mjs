#!/usr/bin/env node
/**
 * Cross-SDK verification helper for ROAR Protocol interop tests.
 *
 * Usage:
 *   node tests/verify_cross_sdk.mjs <message-json-path> <hmac-secret>
 *
 * Reads a ROARMessage JSON file, verifies its HMAC-SHA256 signature using the
 * TypeScript SDK, and exits 0 on success or 1 on failure.
 *
 * This script uses source imports (../../ts/src/) so it works without a build
 * step. It is only used for internal conformance testing.
 */

import { readFileSync } from "fs";
import { verifyMessage } from "../ts/src/message.js";

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

const ok = verifyMessage(wire, secret, { maxAgeSeconds: 86400 });

if (ok) {
  console.log("ROAR cross-SDK verify: OK");
  process.exit(0);
} else {
  console.error("ROAR cross-SDK verify: FAILED — signature mismatch or stale timestamp");
  process.exit(1);
}
