#!/usr/bin/env node
/**
 * Verify a ROAR message HMAC-SHA256 signature using the TypeScript SDK.
 *
 * Reads signed JSON from stdin. Exits 0 if valid, 1 if invalid.
 * Requires: npm run build in ts/ before running.
 */
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../..");

const types = await import(pathToFileURL(resolve(ROOT, "ts/dist/types.js")).href);
const sdk = await import(pathToFileURL(resolve(ROOT, "ts/dist/message.js")).href);

const secret = process.argv[2];
if (!secret) {
  console.error("Usage: node ts_verify_message.mjs <secret>");
  process.exit(1);
}

let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;

const wire = JSON.parse(input);
const msg = types.messageFromWire(wire);
const valid = sdk.verifyMessage(msg, secret, 0);
console.log(valid ? "VALID" : "INVALID");
process.exit(valid ? 0 : 1);
