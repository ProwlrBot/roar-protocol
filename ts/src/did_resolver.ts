/**
 * ROAR Protocol — Minimal DID resolver for did:key and did:web methods.
 *
 * SECURITY: Resolution failures always throw DIDResolutionError, never return null silently.
 * Callers should catch DIDResolutionError and reject the operation.
 *
 * SSRF protection: did:web URLs are restricted to HTTPS and validated
 * against a private-IP blocklist before fetching.
 *
 * Mirrors python/src/roar_sdk/did_resolver.py exactly.
 */

import * as https from "https";
import * as net from "net";
import { didKeyToPublicKey } from "./did_key.js";
import { didWebToUrl } from "./did_web.js";

export class DIDResolutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DIDResolutionError";
  }
}

// ---------------------------------------------------------------------------
// SSRF guard — private IP ranges
// ---------------------------------------------------------------------------

interface IpRange {
  base: bigint;
  mask: bigint;
  bits: number;
}

function parseIpRange(cidr: string): IpRange {
  const [addr, bits] = cidr.split("/");
  const prefixLen = parseInt(bits, 10);
  if (net.isIPv4(addr)) {
    const parts = addr.split(".").map(Number);
    const base =
      BigInt(parts[0]) * 16777216n +
      BigInt(parts[1]) * 65536n +
      BigInt(parts[2]) * 256n +
      BigInt(parts[3]);
    const mask = prefixLen === 0 ? 0n : (((1n << BigInt(prefixLen)) - 1n) << BigInt(32 - prefixLen));
    return { base: base & mask, mask, bits: prefixLen };
  } else {
    // IPv6: convert to bigint
    const expanded = expandIPv6(addr);
    const groups = expanded.split(":").map((g) => parseInt(g, 16));
    let base = 0n;
    for (const g of groups) {
      base = (base << 16n) | BigInt(g);
    }
    const mask = prefixLen === 0 ? 0n : (((1n << BigInt(prefixLen)) - 1n) << BigInt(128 - prefixLen));
    return { base: base & mask, mask, bits: prefixLen };
  }
}

function expandIPv6(addr: string): string {
  // Expand :: shorthand
  if (addr.includes("::")) {
    const halves = addr.split("::");
    const left = halves[0] ? halves[0].split(":") : [];
    const right = halves[1] ? halves[1].split(":") : [];
    const missing = 8 - left.length - right.length;
    const middle = Array(missing).fill("0");
    return [...left, ...middle, ...right].join(":");
  }
  return addr;
}

function ipToBigInt(ip: string): { value: bigint; isV4: boolean } {
  if (net.isIPv4(ip)) {
    const parts = ip.split(".").map(Number);
    const value =
      BigInt(parts[0]) * 16777216n +
      BigInt(parts[1]) * 65536n +
      BigInt(parts[2]) * 256n +
      BigInt(parts[3]);
    return { value, isV4: true };
  } else {
    const expanded = expandIPv6(ip);
    const groups = expanded.split(":").map((g) => parseInt(g, 16));
    let value = 0n;
    for (const g of groups) {
      value = (value << 16n) | BigInt(g);
    }
    return { value, isV4: false };
  }
}

const PRIVATE_RANGES_V4 = [
  "10.0.0.0/8",
  "172.16.0.0/12",
  "192.168.0.0/16",
  "127.0.0.0/8",
  "169.254.0.0/16",
].map(parseIpRange);

const PRIVATE_RANGES_V6 = [
  "::1/128",
  "fc00::/7",
  "fe80::/10",
].map(parseIpRange);

function isPrivateIp(ip: string): boolean {
  try {
    const { value, isV4 } = ipToBigInt(ip);
    const ranges = isV4 ? PRIVATE_RANGES_V4 : PRIVATE_RANGES_V6;
    return ranges.some((range) => (value & range.mask) === range.base);
  } catch {
    return true; // fail closed
  }
}

/**
 * Resolve a hostname to its IP addresses and check if any is private.
 * Returns true if the hostname is private/blocked (fail closed on error).
 */
async function isPrivateHostname(hostname: string): Promise<boolean> {
  return new Promise((resolve) => {
    const { lookup } = require("dns");
    lookup(hostname, { all: true }, (err: Error | null, addresses: { address: string }[]) => {
      if (err || !addresses || addresses.length === 0) {
        resolve(true); // fail closed
        return;
      }
      resolve(addresses.some((a) => isPrivateIp(a.address)));
    });
  });
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Resolve a DID to a hex-encoded Ed25519 public key (64-char, 32 bytes).
 *
 * Supports:
 * - did:key:z...  (multibase-encoded Ed25519 key, no network fetch)
 * - did:web:domain  (HTTPS fetch of DID document)
 *
 * Throws DIDResolutionError on any failure.
 */
export async function resolveDidToPublicKey(
  did: string,
  timeoutMs = 5000,
): Promise<string> {
  if (did.startsWith("did:key:")) {
    return resolveDidKey(did);
  } else if (did.startsWith("did:web:")) {
    return resolveDidWeb(did, timeoutMs);
  } else {
    throw new DIDResolutionError(
      `Cannot resolve DID '${did}': unsupported method. ` +
        "Only did:key and did:web are resolvable without a registry.",
    );
  }
}

// ---------------------------------------------------------------------------
// did:key resolution
// ---------------------------------------------------------------------------

function resolveDidKey(did: string): string {
  try {
    const keyBytes = didKeyToPublicKey(did);
    return Buffer.from(keyBytes).toString("hex");
  } catch (e) {
    throw new DIDResolutionError(`Failed to decode did:key '${did}': ${e}`);
  }
}

// ---------------------------------------------------------------------------
// did:web resolution
// ---------------------------------------------------------------------------

async function resolveDidWeb(did: string, timeoutMs: number): Promise<string> {
  let url: string;
  try {
    url = didWebToUrl(did);
  } catch (e) {
    throw new DIDResolutionError(`Failed to build did:web URL for '${did}': ${e}`);
  }

  if (!url.startsWith("https://")) {
    throw new DIDResolutionError(`did:web must resolve to HTTPS, got: ${url}`);
  }

  // SSRF guard
  const { URL } = await import("url");
  const parsed = new URL(url);
  const hostname = parsed.hostname;
  if (!hostname) {
    throw new DIDResolutionError(`did:web URL has no hostname: ${url}`);
  }
  if (await isPrivateHostname(hostname)) {
    throw new DIDResolutionError(
      `did:web hostname '${hostname}' resolves to a private/internal address`,
    );
  }

  const doc = await fetchDIDDocument(url, timeoutMs);
  return extractEd25519Key(doc, did);
}

function fetchDIDDocument(url: string, timeoutMs: number): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const req = https.get(
      url,
      {
        headers: { "User-Agent": "ROAR-DID-Resolver/0.3" },
        timeout: timeoutMs,
      },
      (res) => {
        if (res.statusCode !== 200) {
          reject(
            new DIDResolutionError(
              `DID document fetch returned HTTP ${res.statusCode}`,
            ),
          );
          res.resume();
          return;
        }
        const chunks: Buffer[] = [];
        let totalBytes = 0;
        const MAX_BYTES = 65536; // 64 KiB
        res.on("data", (chunk: Buffer) => {
          totalBytes += chunk.length;
          if (totalBytes > MAX_BYTES) {
            req.destroy();
            reject(new DIDResolutionError("DID document exceeds 64 KiB size limit"));
            return;
          }
          chunks.push(chunk);
        });
        res.on("end", () => {
          try {
            const body = Buffer.concat(chunks).toString("utf-8");
            const doc = JSON.parse(body) as Record<string, unknown>;
            resolve(doc);
          } catch (e) {
            reject(new DIDResolutionError(`Failed to parse DID document JSON: ${e}`));
          }
        });
        res.on("error", (e) => {
          reject(new DIDResolutionError(`Error reading DID document response: ${e}`));
        });
      },
    );

    req.on("timeout", () => {
      req.destroy();
      reject(new DIDResolutionError(`DID document fetch timed out after ${timeoutMs}ms`));
    });

    req.on("error", (e) => {
      reject(new DIDResolutionError(`Failed to fetch DID document: ${e}`));
    });
  });
}

function extractEd25519Key(doc: Record<string, unknown>, did: string): string {
  const methods = (doc["verificationMethod"] as unknown[]) ?? [];
  for (const method of methods) {
    const m = method as Record<string, unknown>;

    // publicKeyMultibase (base58btc z-prefix)
    const pmb = m["publicKeyMultibase"] as string | undefined;
    if (pmb && pmb.startsWith("z")) {
      try {
        // Re-use the same base58 decode logic from did_key.ts
        const keyBytes = didKeyToPublicKey("did:key:" + pmb);
        return Buffer.from(keyBytes).toString("hex");
      } catch {
        // Try other methods
      }
    }

    // publicKeyHex directly
    const pkh = m["publicKeyHex"] as string | undefined;
    if (pkh && pkh.length === 64) {
      return pkh;
    }

    // publicKeyJwk (x field = base64url-encoded key)
    const jwk = m["publicKeyJwk"] as Record<string, string> | undefined;
    if (jwk && jwk["crv"] === "Ed25519" && jwk["x"]) {
      try {
        const keyBytes = Buffer.from(jwk["x"], "base64url");
        if (keyBytes.length === 32) {
          return keyBytes.toString("hex");
        }
      } catch {
        // Try other methods
      }
    }
  }

  throw new DIDResolutionError(
    `No Ed25519 verification method found in DID document for '${did}'`,
  );
}
