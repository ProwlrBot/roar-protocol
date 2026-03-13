# ROAR Protocol TypeScript SDK — Security Audit

**Date:** 2026-03-13
**Auditor:** kdairatchi
**Scope:** All TypeScript source files under `ts/src/` (16 files, ~1 100 LOC)
**Baseline:** 30/30 golden conformance tests passing; `npx tsc --noEmit` clean

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| Critical | 0 | — |
| High | 2 | Yes |
| Medium | 5 | No (documented below) |
| Low | 3 | No (documented below) |
| Info | 0 | — |

No Critical findings. Two High findings (timing side-channels on secret tokens) were fixed in this commit. The remaining Medium/Low findings are documented below with recommended fixes.

---

## Findings

### [FIXED] HIGH-1 — Timing side-channel in HTTP Bearer token comparison

**File:** `ts/src/router.ts` (function `_checkAuth`, original line ~214)

**Description:**
The HTTP Authorization header was compared to the expected Bearer token using string equality (`===`).
JavaScript string equality short-circuits on the first differing byte. An attacker who can measure response latency with sufficient precision can binary-search for the correct token one character at a time.

**Fix applied:**
Replaced with `crypto.timingSafeEqual` after converting both operands to `Buffer`. Length inequality returns `false` immediately (which is safe — length leaks only that the lengths differ, not the secret's content).

---

### [FIXED] HIGH-2 — Timing side-channel in WebSocket auth frame comparison

**File:** `ts/src/router.ts` (WebSocket `handleUpgrade` data handler, original line ~398)

**Description:**
The WebSocket auth frame token was compared with string equality (`===`), same as HIGH-1.
This timing oracle is exploitable over a local or low-latency network.

**Fix applied:**
Replaced with `crypto.timingSafeEqual` using the same pattern as HIGH-1.

---

### MEDIUM-1 — `verifyToken` does not verify expiry or use_count

**File:** `ts/src/delegation.ts`, line 181

**Description:**
`verifyToken` only validates the Ed25519 signature. Its JSDoc comment explicitly states it "does NOT check expiry or use count", but there is no single combined function that verifies all three concerns together. Callers who call only `verifyToken` will accept expired or exhausted tokens.

**Recommended fix:**
Add a combined helper:
```ts
export function verifyAndValidateToken(
  token: DelegationToken,
  delegatorPublicKey: string,
): boolean {
  return verifyToken(token, delegatorPublicKey) && isTokenValid(token);
}
```
Or update `verifyToken` to accept a `checkValidity = true` parameter and call `isTokenValid` internally.

---

### MEDIUM-2 — Race condition in `consumeToken`

**File:** `ts/src/delegation.ts`, lines 106–110

**Description:**
`consumeToken` is a non-atomic read-modify-write. If two concurrent async call chains both reach the guard check before either increments `use_count`, both will return `true` and over-consume the token. In Node.js this is only a risk when the token object is shared across `await` boundaries, but the SDK does not prevent that.

**Recommended fix:**
Document clearly that `consumeToken` is not safe for concurrent callers sharing the same object, or protect it with a promise-based mutex.

---

### MEDIUM-3 — WebSocket server frame parser: 64-bit length field ignores high 32 bits

**File:** `ts/src/router.ts`, line 112

**Description:**
For frames with 8-byte extended length (`payloadLen === 127`), only the low 32 bits are read. There is no rejection of frames whose high 32 bits are non-zero. A malformed frame with a large 64-bit value would be silently treated as having a smaller payload, causing incorrect buffer slicing.

**Recommended fix:**
Read and validate the high 32-bit word; reject (close) the connection if it is non-zero.

---

### MEDIUM-4 — WebSocket server: no maximum frame payload size

**File:** `ts/src/router.ts`, `parseWsFrames` function

**Description:**
There is no cap on `payloadLen`. A client can declare a multi-gigabyte frame (up to 2^32−1 bytes). The buffer guard prevents reading past existing data, but `rxBuf` accumulates all incoming bytes indefinitely until a complete frame arrives, enabling memory exhaustion DoS.

**Recommended fix:**
Add a constant (e.g. 1 MiB) and close the connection if a declared `payloadLen` exceeds it.

---

### MEDIUM-5 — WebSocket client frame parser: same 64-bit truncation

**File:** `ts/src/websocket.ts`, line 189

**Description:**
Same as MEDIUM-3 — `this._buffer.readUInt32BE(6)` discards the high 32 bits silently.

**Recommended fix:**
Same pattern as MEDIUM-3.

---

### LOW-1 — Path traversal in `SqliteAgentDirectory` constructor

**File:** `ts/src/sqlite_directory.ts`, line 27

**Description:**
`dbPath` is passed directly to `new DatabaseSync(dbPath)` with no canonicalization or validation. An application that passes user-controlled input to the constructor can be tricked into opening an arbitrary file path.

**Recommended fix:**
Canonicalize with `path.resolve()` and optionally assert the result starts within an allowed base directory. At minimum add a JSDoc warning.

---

### LOW-2 — Unbounded buffer growth in `stdio.ts` `readLine` on no-newline input

**File:** `ts/src/stdio.ts`, lines 24–28

**Description:**
If the remote peer sends data without ever sending a newline, `buf` grows without bound until the process runs out of memory or stdin closes.

**Recommended fix:**
Add a byte limit (e.g. 16 MiB) and reject with an error if exceeded.

---

### LOW-3 — X-Forwarded-For header trusted without validation for rate limiting

**File:** `ts/src/router.ts`, lines 195–199

**Description:**
Any client can spoof the `X-Forwarded-For` header to appear as a different IP address, bypassing per-IP rate limiting entirely.

**Recommended fix:**
Add a `trustedProxy?: boolean` option (default `false`). Only trust `X-Forwarded-For` when set to `true`. Otherwise, always use `req.socket.remoteAddress`.

---

## What was checked

| Area | Files | Status |
|------|-------|--------|
| Crypto module usage | All `.ts` | Only `node:crypto` / `crypto` — no homebrew or weak algorithms |
| Timing side-channels | `message.ts`, `signing.ts`, `router.ts` | `message.ts`/`signing.ts` correct; `router.ts` fixed (HIGH-1, HIGH-2) |
| Key material in logs/errors | All `.ts` | No private key material in error strings |
| HMAC/Ed25519 signing correctness | `message.ts`, `signing.ts`, `delegation.ts` | Canonical JSON body correct; DER key wrapping correct; null algorithm for Ed25519 correct |
| JSON.parse on untrusted input | `router.ts`, `server.ts`, `websocket.ts`, `stdio.ts` | All wrapped in try/catch |
| Dynamic code execution | All `.ts` | None found |
| Shell injection via child_process | All `.ts` | No child_process usage — zero risk |
| Token bucket integer overflow | `router.ts` | No overflow; floating-point, clamped with Math.min |
| SSE connection limit | `router.ts` | `_sseCount >= maxSse` enforced |
| WS frame length bounds | `router.ts`, `websocket.ts` | Payload guard present; no max cap (MEDIUM-4); 64-bit truncation (MEDIUM-3, MEDIUM-5) |
| `delegation.ts` `verifyToken` field coverage | `delegation.ts` | Signature only — expiry/use_count not checked (MEDIUM-1) |
| Delegation signing body canonicality | `delegation.ts` | Correct — `signature` and `use_count` excluded |
| `consumeToken` concurrency | `delegation.ts` | Non-atomic (MEDIUM-2) |
| SQL injection in `sqlite_directory.ts` | `sqlite_directory.ts` | All queries use parameterized `?` placeholders — no risk |
| File path traversal | `sqlite_directory.ts` | LOW-1 |
| stdio unbounded buffer | `stdio.ts` | LOW-2 |
| WebSocket RFC 6455 handshake | `router.ts`, `websocket.ts` | SHA-1 GUID concatenation and base64 accept key correct |
| Server frame masking | `router.ts` | Server correctly sends UNMASKED frames (RFC 6455 §5.1) |
| Client frame masking | `websocket.ts` | Client correctly sends MASKED frames with `crypto.randomBytes(4)` |
