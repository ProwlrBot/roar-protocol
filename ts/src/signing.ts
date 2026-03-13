/**
 * ROAR Protocol — Ed25519 asymmetric signing for Layer 1 identity.
 *
 * Uses Node.js 18+ built-in crypto — no external dependencies.
 * Mirrors python/src/roar_sdk/signing.py exactly.
 *
 * Signing format: auth.signature = "ed25519:<base64url>"
 * The signing body is identical to HMAC signing (pythonJsonDumps canonical JSON).
 */

import {
  generateKeyPairSync,
  createPrivateKey,
  createPublicKey,
  sign as cryptoSign,
  verify as cryptoVerify,
} from "crypto";
import { pythonJsonDumps } from "./message.js";
import { AgentIdentity, ROARMessage } from "./types.js";

// ---------------------------------------------------------------------------
// Key generation
// ---------------------------------------------------------------------------

export interface Ed25519KeyPair {
  privateKeyHex: string; // 64-char hex (32 bytes)
  publicKeyHex: string;  // 64-char hex (32 bytes)
}

/** Generate an Ed25519 key pair for an agent identity. */
export function generateEd25519KeyPair(): Ed25519KeyPair {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");

  // Export as raw 32-byte buffers
  const privRaw = privateKey.export({ type: "pkcs8", format: "der" });
  const pubRaw = publicKey.export({ type: "spki", format: "der" });

  // PKCS8 DER for Ed25519: last 32 bytes are the raw key
  const privateKeyHex = privRaw.slice(-32).toString("hex");
  // SPKI DER for Ed25519: last 32 bytes are the raw key
  const publicKeyHex = pubRaw.slice(-32).toString("hex");

  return { privateKeyHex, publicKeyHex };
}

// ---------------------------------------------------------------------------
// Signing body (same canonical JSON as HMAC)
// ---------------------------------------------------------------------------

function signingBodyEd25519(msg: ROARMessage): Buffer {
  const body = pythonJsonDumps({
    id: msg.id,
    from: msg.from_identity.did,
    to: msg.to_identity.did,
    intent: msg.intent,
    payload: msg.payload,
    context: msg.context,
    timestamp: (msg.auth["timestamp"] as number) ?? msg.timestamp,
  });
  return Buffer.from(body, "utf-8");
}

/** Convert a 32-byte raw hex key to a Node.js KeyObject (PKCS8 DER). */
function privateKeyFromHex(hex: string): ReturnType<typeof createPrivateKey> {
  const raw = Buffer.from(hex, "hex");
  // PKCS8 DER wrapper for Ed25519 private key
  const pkcs8Header = Buffer.from("302e020100300506032b657004220420", "hex");
  const der = Buffer.concat([pkcs8Header, raw]);
  return createPrivateKey({ key: der, format: "der", type: "pkcs8" });
}

/** Convert a 32-byte raw hex key to a Node.js KeyObject (SPKI DER). */
function publicKeyFromHex(hex: string): ReturnType<typeof createPublicKey> {
  const raw = Buffer.from(hex, "hex");
  // SPKI DER wrapper for Ed25519 public key
  const spkiHeader = Buffer.from("302a300506032b6570032100", "hex");
  const der = Buffer.concat([spkiHeader, raw]);
  return createPublicKey({ key: der, format: "der", type: "spki" });
}

// ---------------------------------------------------------------------------
// Sign / Verify
// ---------------------------------------------------------------------------

/**
 * Sign a ROARMessage with an Ed25519 private key.
 * Sets auth.signature = "ed25519:<base64url>" and auth.public_key = publicKeyHex.
 * Returns the message (mutated in place) for chaining.
 */
export function signEd25519(msg: ROARMessage, privateKeyHex: string): ROARMessage {
  const privKey = privateKeyFromHex(privateKeyHex);
  // Derive public key from private key
  const pubKey = createPublicKey(privKey);
  const pubRaw = pubKey.export({ type: "spki", format: "der" }) as Buffer;
  const publicKeyHex = pubRaw.slice(-32).toString("hex");

  msg.auth = { timestamp: Date.now() / 1000 };
  const body = signingBodyEd25519(msg);
  const rawSig = cryptoSign(null, body, privKey) as Buffer;
  const sigB64 = rawSig.toString("base64url");

  msg.auth["signature"] = `ed25519:${sigB64}`;
  msg.auth["public_key"] = publicKeyHex;
  return msg;
}

/**
 * Verify an Ed25519 signed ROARMessage.
 * Uses msg.from_identity.public_key by default, or a provided publicKeyHex.
 *
 * @param maxAgeSeconds - 0 = skip age check
 */
export function verifyEd25519(
  msg: ROARMessage,
  maxAgeSeconds = 300,
  publicKeyHexOverride?: string,
): boolean {
  const sigValue = (msg.auth["signature"] as string) ?? "";
  if (!sigValue.startsWith("ed25519:")) return false;

  if (maxAgeSeconds > 0) {
    const msgTime = (msg.auth["timestamp"] as number) ?? 0;
    if (Math.abs(Date.now() / 1000 - msgTime) > maxAgeSeconds) return false;
  }

  const keyHex = publicKeyHexOverride ?? msg.from_identity.public_key ?? "";
  if (!keyHex) return false;

  try {
    const pubKey = publicKeyFromHex(keyHex);
    const b64 = sigValue.slice("ed25519:".length);
    const rawSig = Buffer.from(b64, "base64url");
    const body = signingBodyEd25519(msg);
    return cryptoVerify(null, body, pubKey, rawSig) as boolean;
  } catch {
    return false;
  }
}
