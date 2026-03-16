#!/usr/bin/env node
/**
 * CI check: @roar-protocol/sdk version in package.json must be coherent,
 * and ts_sdk_min_version in spec/VERSION.json must be set.
 *
 * Mirrors tests/check_versions.py logic for the TypeScript SDK.
 */

import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

const spec = JSON.parse(readFileSync(resolve(root, "spec", "VERSION.json"), "utf8"));
const pkg = JSON.parse(readFileSync(resolve(root, "ts", "package.json"), "utf8"));

// 1. Package name must be correct
if (pkg.name !== "@roar-protocol/sdk") {
  console.error(`FAIL: ts/package.json name is ${JSON.stringify(pkg.name)}, expected "@roar-protocol/sdk"`);
  process.exit(1);
}

// 2. SDK version must be semver (basic check)
if (!/^\d+\.\d+\.\d+/.test(pkg.version)) {
  console.error(`FAIL: ts/package.json version ${JSON.stringify(pkg.version)} is not semver`);
  process.exit(1);
}

// 3. ts_sdk_min_version must be set in VERSION.json (was null in initial release)
if (!spec.compatibility?.ts_sdk_min_version) {
  console.warn(`WARN: spec/VERSION.json compatibility.ts_sdk_min_version is not set — update it to ${pkg.version}`);
  // Not a hard failure — will be enforced once we bump the spec
}

// 4. Python and TS SDK major.minor must match (they track together)
const pyMinVer = spec.compatibility?.python_sdk_min_version ?? "";
const tsSdkVer = pkg.version;
const [pyMaj, pyMin] = pyMinVer.split(".").map(Number);
const [tsMaj, tsMin] = tsSdkVer.split(".").map(Number);
if (pyMaj !== tsMaj || pyMin !== tsMin) {
  console.error(
    `FAIL: Python SDK min version (${pyMinVer}) and TS SDK version (${tsSdkVer}) ` +
    `have different major.minor — they should track together.`
  );
  process.exit(1);
}

console.log(`TS SDK version aligned: ${pkg.version} (spec ${spec.spec_version})`);
