#!/usr/bin/env node
/**
 * CI check: verify spec version and SDK versions are aligned.
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

function parseVersion(v) {
  return v.split(".").map(Number);
}

function versionLt(a, b) {
  const pa = parseVersion(a);
  const pb = parseVersion(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? 0;
    const y = pb[i] ?? 0;
    if (x < y) return true;
    if (x > y) return false;
  }
  return false;
}

const errors = [];

// Read spec version
const spec = JSON.parse(readFileSync(resolve(ROOT, "spec/VERSION.json"), "utf8"));
const specVer = spec.spec_version;
const pyMin = spec.compatibility.python_sdk_min_version;
const tsMin = spec.compatibility.ts_sdk_min_version;

// Read Python SDK version from pyproject.toml
const pyproject = readFileSync(resolve(ROOT, "python/pyproject.toml"), "utf8");
const pyMatch = pyproject.match(/^version\s*=\s*"([^"]+)"/m);
const pyVer = pyMatch?.[1];
if (!pyVer) {
  errors.push("Could not find version in python/pyproject.toml");
} else if (versionLt(pyVer, pyMin)) {
  errors.push(`Python SDK ${pyVer} < required minimum ${pyMin} for spec ${specVer}`);
}

// Read TypeScript SDK version from package.json
const tsPkg = JSON.parse(readFileSync(resolve(ROOT, "ts/package.json"), "utf8"));
const tsVer = tsPkg.version;
if (versionLt(tsVer, tsMin)) {
  errors.push(`TypeScript SDK ${tsVer} < required minimum ${tsMin} for spec ${specVer}`);
}

// Report
console.log(`Spec version:      ${specVer}`);
console.log(`Python SDK:        ${pyVer} (min: ${pyMin})`);
console.log(`TypeScript SDK:    ${tsVer} (min: ${tsMin})`);

if (errors.length > 0) {
  console.log("\nALIGNMENT ERRORS:");
  errors.forEach((e) => console.log(`  - ${e}`));
  process.exit(1);
}

console.log("\nAll versions aligned.");
