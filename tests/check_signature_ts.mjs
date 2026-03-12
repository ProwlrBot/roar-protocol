#!/usr/bin/env node
/**
 * CI check: TypeScript SDK canonical body and HMAC must match signature.json.
 *
 * Mirrors check_signature.py but uses the JS implementation of
 * pythonJsonDumps so the two implementations stay in lock-step.
 *
 * Run: node tests/check_signature_ts.mjs
 * Requires Node.js 18+ (built-in crypto, no npm install needed).
 */

import { createHmac } from "crypto";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const GOLDEN = join(__dirname, "conformance", "golden", "signature.json");
const data = JSON.parse(readFileSync(GOLDEN, "utf8"));

// ---------------------------------------------------------------------------
// Replicate pythonJsonDumps from packages/roar-sdk-ts/src/message.ts
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
// Verify canonical JSON
// ---------------------------------------------------------------------------
const canonical = pythonJsonDumps(data.inputs);

if (canonical !== data.canonical_json) {
  console.error("FAIL: canonical JSON has changed");
  console.error("  expected:", data.canonical_json);
  console.error("  got:     ", canonical);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Verify HMAC
// ---------------------------------------------------------------------------
const hmac = createHmac("sha256", data.secret);
hmac.update(canonical);
const actual = "hmac-sha256:" + hmac.digest("hex");

if (actual !== data.expected_signature) {
  console.error("FAIL: HMAC value has changed");
  console.error("  expected:", data.expected_signature);
  console.error("  got:     ", actual);
  process.exit(1);
}

console.log("signature.json stable (TS):", actual.slice(0, 52) + "...");
