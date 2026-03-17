/**
 * ROAR Protocol — Browser SDK Ed25519 asymmetric signing.
 *
 * Uses the Web Crypto API for Ed25519 operations.
 * All functions are async because Web Crypto is async.
 *
 * Signing format: auth.signature = "ed25519:<base64url>"
 * The signing body is identical to the Node SDK (pythonJsonDumps canonical JSON).
 *
 * Note: Ed25519 support in Web Crypto requires Chrome 113+, Firefox 130+,
 * Safari 17+, or Edge 113+. For older browsers, a polyfill is needed.
 */

import { pythonJsonDumps } from "./message.js";
import { AgentIdentity, ROARMessage } from "./types.js";

// ---------------------------------------------------------------------------
// Key pair type
// ---------------------------------------------------------------------------

export interface Ed25519KeyPair {
  privateKeyHex: string; // 64-char hex (32 bytes)
  publicKeyHex: string;  // 64-char hex (32 bytes)
}

// ---------------------------------------------------------------------------
// Encoding helpers
// ---------------------------------------------------------------------------

const encoder = new TextEncoder();

function bufferToHex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

function hexToBuffer(hex: string): Uint8Array {
  const bytes = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    bytes[i / 2] = parseInt(hex.substring(i, i + 2), 16);
  }
  return bytes;
}

/** Encode bytes to base64url (no padding). */
function toBase64url(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Decode base64url to Uint8Array. */
function fromBase64url(b64: string): Uint8Array {
  const padded = b64.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

// ---------------------------------------------------------------------------
// PKCS8 / SPKI DER wrappers for Ed25519
// ---------------------------------------------------------------------------

/** PKCS8 DER header for Ed25519 private key (prepend to 32-byte raw key). */
const PKCS8_ED25519_HEADER = new Uint8Array([
  0x30, 0x2e, 0x02, 0x01, 0x00, 0x30, 0x05, 0x06,
  0x03, 0x2b, 0x65, 0x70, 0x04, 0x22, 0x04, 0x20,
]);

/** SPKI DER header for Ed25519 public key (prepend to 32-byte raw key). */
const SPKI_ED25519_HEADER = new Uint8Array([
  0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65,
  0x70, 0x03, 0x21, 0x00,
]);

function buildPkcs8(rawPrivate: Uint8Array): Uint8Array {
  const der = new Uint8Array(PKCS8_ED25519_HEADER.length + rawPrivate.length);
  der.set(PKCS8_ED25519_HEADER, 0);
  der.set(rawPrivate, PKCS8_ED25519_HEADER.length);
  return der;
}

function buildSpki(rawPublic: Uint8Array): Uint8Array {
  const der = new Uint8Array(SPKI_ED25519_HEADER.length + rawPublic.length);
  der.set(SPKI_ED25519_HEADER, 0);
  der.set(rawPublic, SPKI_ED25519_HEADER.length);
  return der;
}

// ---------------------------------------------------------------------------
// Key generation
// ---------------------------------------------------------------------------

/**
 * Generate an Ed25519 key pair using Web Crypto.
 *
 * Returns raw 32-byte keys as hex strings, compatible with the Node SDK format.
 */
export async function generateKeyPair(): Promise<Ed25519KeyPair> {
  const keyPair = await crypto.subtle.generateKey(
    "Ed25519",
    true, // extractable
    ["sign", "verify"],
  );

  // Export as PKCS8/SPKI DER, then extract the raw 32 bytes
  const pkcs8 = new Uint8Array(
    await crypto.subtle.exportKey("pkcs8", keyPair.privateKey),
  );
  const spki = new Uint8Array(
    await crypto.subtle.exportKey("spki", keyPair.publicKey),
  );

  // Raw key is the last 32 bytes of each DER encoding
  const privateKeyHex = bufferToHex(pkcs8.slice(-32));
  const publicKeyHex = bufferToHex(spki.slice(-32));

  return { privateKeyHex, publicKeyHex };
}

// ---------------------------------------------------------------------------
// Signing body (same canonical JSON as HMAC)
// ---------------------------------------------------------------------------

function signingBodyEd25519(msg: ROARMessage): Uint8Array {
  const body = pythonJsonDumps({
    id: msg.id,
    from: msg.from_identity.did,
    to: msg.to_identity.did,
    intent: msg.intent,
    payload: msg.payload,
    context: msg.context,
    timestamp: (msg.auth["timestamp"] as number) ?? msg.timestamp,
  });
  return encoder.encode(body);
}

// ---------------------------------------------------------------------------
// Sign / Verify
// ---------------------------------------------------------------------------

/**
 * Sign a ROARMessage with an Ed25519 private key using Web Crypto.
 *
 * Sets auth.signature = "ed25519:<base64url>" and auth.public_key.
 * Returns the message (mutated in place) for chaining.
 *
 * @param msg - The message to sign
 * @param privateKeyHex - 64-char hex string (32 bytes) of the Ed25519 private key
 */
export async function signEd25519(
  msg: ROARMessage,
  privateKeyHex: string,
): Promise<ROARMessage> {
  const rawPrivate = hexToBuffer(privateKeyHex);
  const pkcs8Der = buildPkcs8(rawPrivate);

  const privateKey = await crypto.subtle.importKey(
    "pkcs8",
    pkcs8Der,
    "Ed25519",
    true, // extractable so we can derive the public key
    ["sign"],
  );

  // Derive public key by re-exporting the private key's PKCS8, importing as
  // a key pair is not directly supported. Instead, export the JWK which
  // contains the public component.
  const jwk = await crypto.subtle.exportKey("jwk", privateKey);
  // The "x" field in JWK is the base64url-encoded public key
  const publicKeyBytes = fromBase64url(jwk.x!);
  const publicKeyHex = bufferToHex(publicKeyBytes);

  msg.auth = { timestamp: Date.now() / 1000 };
  const body = signingBodyEd25519(msg);

  const rawSig = new Uint8Array(
    await crypto.subtle.sign("Ed25519", privateKey, body),
  );
  const sigB64 = toBase64url(rawSig);

  msg.auth["signature"] = `ed25519:${sigB64}`;
  msg.auth["public_key"] = publicKeyHex;
  return msg;
}

/**
 * Verify an Ed25519 signed ROARMessage using Web Crypto.
 *
 * Uses msg.from_identity.public_key by default, or a provided publicKeyHex.
 *
 * @param maxAgeSeconds - 0 = skip age check
 */
export async function verifyEd25519(
  msg: ROARMessage,
  maxAgeSeconds = 300,
  publicKeyHexOverride?: string,
): Promise<boolean> {
  const sigValue = (msg.auth["signature"] as string) ?? "";
  if (!sigValue.startsWith("ed25519:")) return false;

  if (maxAgeSeconds > 0) {
    const msgTime = (msg.auth["timestamp"] as number) ?? 0;
    if (Math.abs(Date.now() / 1000 - msgTime) > maxAgeSeconds) return false;
  }

  const keyHex = publicKeyHexOverride ?? msg.from_identity.public_key ?? "";
  if (!keyHex) return false;

  try {
    const rawPublic = hexToBuffer(keyHex);
    const spkiDer = buildSpki(rawPublic);

    const publicKey = await crypto.subtle.importKey(
      "spki",
      spkiDer,
      "Ed25519",
      false,
      ["verify"],
    );

    const b64 = sigValue.slice("ed25519:".length);
    const rawSig = fromBase64url(b64);
    const body = signingBodyEd25519(msg);

    return await crypto.subtle.verify("Ed25519", publicKey, rawSig, body);
  } catch {
    return false;
  }
}
