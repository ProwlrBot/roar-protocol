#!/usr/bin/env node
/**
 * Sign a ROAR message with HMAC-SHA256 using the TypeScript SDK.
 *
 * Reads JSON from stdin, signs it, writes signed JSON to stdout.
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
  console.error("Usage: node ts_sign_message.mjs <secret>");
  process.exit(1);
}

let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;

const wire = JSON.parse(input);
const msg = types.messageFromWire(wire);
const signed = sdk.signMessage(msg, secret);
process.stdout.write(JSON.stringify(signed));
