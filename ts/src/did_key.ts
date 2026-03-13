/**
 * ROAR Protocol — did:key method for ephemeral, self-certifying agent identities.
 *
 * A did:key is derived entirely from a public key, requiring no external
 * registry. Ideal for ephemeral agents that need verifiable identity for
 * a single session or short-lived task.
 *
 * Format: did:key:z<base58btc-multicodec-ed25519-pubkey>
 *
 * No external dependencies — base58btc implemented from scratch.
 *
 * Ref: https://w3c-ccg.github.io/did-method-key/
 */

// Multicodec prefix for Ed25519 public key: 0xed 0x01
const ED25519_MULTICODEC = new Uint8Array([0xed, 0x01]);

// Bitcoin base58 alphabet (base58btc)
const BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";

/**
 * Encode bytes to base58btc (Bitcoin alphabet).
 */
function base58Encode(input: Uint8Array): string {
  // Count leading zero bytes
  let leadingZeros = 0;
  for (let i = 0; i < input.length; i++) {
    if (input[i] !== 0) break;
    leadingZeros++;
  }

  // Convert bytes to a big integer (as array of digits in base 58)
  const digits: number[] = [0];
  for (let i = 0; i < input.length; i++) {
    let carry = input[i];
    for (let j = 0; j < digits.length; j++) {
      carry += digits[j] << 8;
      digits[j] = carry % 58;
      carry = Math.floor(carry / 58);
    }
    while (carry > 0) {
      digits.push(carry % 58);
      carry = Math.floor(carry / 58);
    }
  }

  // Build result string: leading '1's for leading zero bytes, then digits reversed
  let result = "1".repeat(leadingZeros);
  for (let i = digits.length - 1; i >= 0; i--) {
    result += BASE58_ALPHABET[digits[i]];
  }
  return result;
}

/**
 * Decode base58btc (Bitcoin alphabet) to bytes.
 */
function base58Decode(input: string): Uint8Array {
  // Count leading '1' characters (map to zero bytes)
  let leadingZeros = 0;
  for (let i = 0; i < input.length; i++) {
    if (input[i] !== "1") break;
    leadingZeros++;
  }

  // Convert base58 digits to bytes
  const bytes: number[] = [0];
  for (let i = 0; i < input.length; i++) {
    const charIdx = BASE58_ALPHABET.indexOf(input[i]);
    if (charIdx < 0) throw new Error(`Invalid base58 character: '${input[i]}'`);
    let carry = charIdx;
    for (let j = 0; j < bytes.length; j++) {
      carry += bytes[j] * 58;
      bytes[j] = carry & 0xff;
      carry >>= 8;
    }
    while (carry > 0) {
      bytes.push(carry & 0xff);
      carry >>= 8;
    }
  }

  // Reverse and prepend leading zero bytes
  const result = new Uint8Array(leadingZeros + bytes.length);
  // leading zeros already 0
  for (let i = 0; i < bytes.length; i++) {
    result[leadingZeros + i] = bytes[bytes.length - 1 - i];
  }
  return result;
}

/**
 * Encode a raw 32-byte Ed25519 public key as a did:key DID.
 *
 * Encoding steps:
 *   1. Prepend multicodec prefix [0xed, 0x01] to the 32-byte key.
 *   2. Encode the result with base58btc.
 *   3. Prepend 'z' (multibase base58btc indicator).
 *   4. Prefix with 'did:key:'.
 */
export function publicKeyToDidKey(publicKeyBytes: Uint8Array): string {
  const multicodec = new Uint8Array(ED25519_MULTICODEC.length + publicKeyBytes.length);
  multicodec.set(ED25519_MULTICODEC, 0);
  multicodec.set(publicKeyBytes, ED25519_MULTICODEC.length);
  return "did:key:z" + base58Encode(multicodec);
}

/**
 * Decode a did:key DID back to the raw 32-byte Ed25519 public key.
 *
 * Inverse of publicKeyToDidKey.
 */
export function didKeyToPublicKey(did: string): Uint8Array {
  if (!did.startsWith("did:key:z")) {
    throw new Error(`Not a valid did:key (must start with 'did:key:z'): ${did}`);
  }
  const encoded = did.slice("did:key:z".length);
  const decoded = base58Decode(encoded);

  // Verify and strip the Ed25519 multicodec prefix [0xed, 0x01]
  if (decoded.length < 2 || decoded[0] !== 0xed || decoded[1] !== 0x01) {
    throw new Error(`did:key does not contain Ed25519 multicodec prefix: ${did}`);
  }
  if (decoded.length !== 2 + 32) {
    throw new Error(`Expected 34 decoded bytes (prefix + 32-byte key), got ${decoded.length}`);
  }
  return decoded.slice(2);
}
