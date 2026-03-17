#!/usr/bin/env node
/**
 * Sign an AgentCard with Ed25519 using the TypeScript SDK.
 *
 * Reads JSON card from stdin, signs it, writes signed card JSON to stdout.
 * Requires: npm run build in ts/ before running.
 */
import { resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "../..");

const signing = await import(pathToFileURL(resolve(ROOT, "ts/dist/signing.js")).href);

const privateKeyHex = process.argv[2];
if (!privateKeyHex) {
  console.error("Usage: node ts_sign_agentcard.mjs <private_key_hex>");
  process.exit(1);
}

let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;

const card = JSON.parse(input);
const attestation = signing.signAgentCard(card, privateKeyHex);
card.attestation = attestation;
process.stdout.write(JSON.stringify(card));
