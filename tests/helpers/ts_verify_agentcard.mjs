#!/usr/bin/env node
/**
 * Verify an AgentCard Ed25519 attestation using the TypeScript SDK.
 *
 * Reads signed card JSON from stdin. Exits 0 if valid, 1 if invalid.
 * Usage: echo '{"identity":..., "attestation":"..."}' | node ts_verify_agentcard.mjs
 */
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../..");

const signing = await import(pathToFileURL(resolve(ROOT, "ts/dist/signing.js")).href);

let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;

const card = JSON.parse(input);
const valid = signing.verifyAgentCard(card);
console.log(valid ? "VALID" : "INVALID");
process.exit(valid ? 0 : 1);
