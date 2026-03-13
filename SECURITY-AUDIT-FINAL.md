# ROAR Protocol TypeScript SDK — Final Security Audit

**Date:** 2026-03-13
**Auditor:** kdairatchi
**Scope:** All TypeScript source files under `ts/src/` (19 files, ~1 500 LOC)
**Baseline after this audit:** 30/30 golden conformance tests passing; `npx tsc --noEmit` clean.

---

## Executive Summary

This final audit covers all files added since the previous audit pass plus a fresh-eye
re-audit of every previously reviewed file.  Two Medium severity findings (unbounded HTTP
POST body accumulation in `server.ts` and `router.ts`) were fixed directly.  All
previously documented High findings remain fixed.  No Critical findings were found in any
file.

---

## Files Added Since Previous Audit

| File | Status |
|------|--------|
| `did_key.ts` | Clean |
| `did_web.ts` | Clean |
| `detect.ts` | Clean |
| `autonomy.ts` | Clean (one Low documented below) |
| `discovery_cache.ts` | Clean |
| `did_document.ts` | Clean |
| `sqlite_directory.ts` | Clean (path.resolve fix previously applied) |

---

## Finding Index

| ID | Severity | File | Status |
|----|----------|------|--------|
| FINAL-M1 | Medium | `server.ts:140` | Fixed in this commit |
| FINAL-M2 | Medium | `router.ts:343` | Fixed in this commit |
| FINAL-L1 | Low | `autonomy.ts` (`_by_grantee`) | Documented, not auto-fixed |
| FINAL-L2 | Low | `sqlite_directory.ts:103` | Documented, not auto-fixed |
| FINAL-L3 | Low | `client.ts:49` | Documented, not auto-fixed |
| PREV-H1 | High | `router.ts` `_checkAuth` | Fixed in previous audit |
| PREV-H2 | High | `router.ts` `handleUpgrade` | Fixed in previous audit |
| PREV-M1 | Medium | `delegation.ts` `verifyToken` | Fixed in previous audit (verifyAndValidateToken added) |
| PREV-M2 | Medium | `delegation.ts` `consumeToken` | Documented (TOCTOU in async callers) |
| PREV-M3 | Medium | `router.ts` WS 64-bit length | Fixed in previous audit |
| PREV-M4 | Medium | `router.ts` WS frame cap | Fixed in previous audit (1 MiB) |
| PREV-M5 | Medium | `websocket.ts` WS 64-bit length | Fixed in previous audit |
| PREV-L1 | Low | `sqlite_directory.ts` path traversal | Fixed in previous audit (path.resolve) |
| PREV-L2 | Low | `stdio.ts` unbounded buffer | Fixed in previous audit (10 MiB cap) |
| PREV-L3 | Low | `router.ts` X-Forwarded-For | Fixed in previous audit (trustProxy flag) |

---

## New Findings (This Audit Pass)

### [FIXED] FINAL-M1 — Unbounded HTTP POST body in `server.ts`

**File:line:** `ts/src/server.ts:140`
**Severity:** Medium

**Issue:**
`server.ts` accumulated the full POST body into a string using `body += chunk` with no
size cap.  An attacker could POST an arbitrarily large body (hundreds of megabytes),
consuming process memory until the Node.js process is OOM-killed.

**Fix applied:**
Added a 1 MiB cap.  On the first `data` event that pushes `bodyBytes` over the limit,
`req.destroy()` is called and a 413 response is sent on the `end` event.

---

### [FIXED] FINAL-M2 — Unbounded HTTP POST body in `router.ts`

**File:line:** `ts/src/router.ts:343`
**Severity:** Medium

**Issue:**
The same pattern as FINAL-M1 appeared in the `POST /roar/message` handler inside
`createROARRouter`.  Rate limiting only fires after the body has been buffered, so a
single high-rate or large-body request could bypass the intended resource protections.

**Fix applied:**
Identical 1 MiB cap with `req.destroy()` and 413 response, consistent with `server.ts`.

---

### FINAL-L1 — `_by_grantee` lists grow unbounded until `cleanup_expired()` is called

**File:line:** `ts/src/autonomy.ts` — `CapabilityDelegation._by_grantee` map
**Severity:** Low

**Issue:**
Every `grant()` call appends a token ID to `_by_grantee.get(grantee)`.  The list is only
compacted when the caller explicitly invokes `cleanup_expired()`.  In a long-running server
that never calls `cleanup_expired()`, the lists grow without bound.  The `_tokens` map has
the same issue.  Authorization and autonomy-level queries skip invalid tokens at runtime,
so correctness is unaffected — only memory usage grows.

**Recommended fix:**
Call `cleanup_expired()` periodically (e.g., on a setInterval or as part of the `grant`
path if `_by_grantee.size > threshold`).  Alternatively, auto-evict inside `grant()`.

---

### FINAL-L2 — `JSON.parse` in `_rowToEntry` is unguarded

**File:line:** `ts/src/sqlite_directory.ts:103`
**Severity:** Low

**Issue:**
`_rowToEntry` calls `JSON.parse(row.card_json)` without a try/catch.  If the `card_json`
column in the database contains malformed JSON (due to external tampering, data migration,
or a storage error), this throws an uncaught exception that propagates to the caller.
Because all data is written by the SDK itself using `JSON.stringify`, exploitation requires
direct database write access — significantly reducing practical severity.

**Recommended fix:**
```ts
private _rowToEntry(row: { card_json: string; ... }): DiscoveryEntry {
  let card: AgentCard;
  try {
    card = JSON.parse(row.card_json) as AgentCard;
  } catch {
    throw new Error(`SqliteAgentDirectory: corrupt card_json for row`);
  }
  return { agent_card: card, ... };
}
```

---

### FINAL-L3 — Unbounded response body accumulation in `client.ts`

**File:line:** `ts/src/client.ts:49`
**Severity:** Low

**Issue:**
`ROARClient.send()` accumulates the HTTP response body with `data += chunk` and no size
cap.  A malicious or misbehaving server could stream an unbounded response.  Because this
is a client-side transport receiving data from a server the caller configured, the threat
model is lower than server-side body accumulation.

**Recommended fix:**
Add a response-body cap (e.g., 4 MiB) and reject with an error if exceeded.

---

## Re-Audit: New Files

### `did_key.ts` — Clean

- **Multicodec prefix `[0xed, 0x01]`:** Correct per W3C DID Key spec.
- **base58Encode / base58Decode:** Standard bignum-in-base-58 implementation.  No
  off-by-one.  Leading zero bytes are preserved correctly as `1` characters in both
  directions.
- **32-byte enforcement:** `didKeyToPublicKey` checks `decoded.length !== 2 + 32` and
  throws.  Tight input validation.
- **No Math.random, no secret material in errors.**

### `did_web.ts` — Clean

- **Port encoding:** `hostPart.replace(":", "%3A")` replaces only the first colon.
  Since a host:port string has exactly one colon, this is correct.  Standard ports (80,
  443) are not present in `hostPart` when the URL has no explicit port — also correct.
- **`%3A` decode:** `parts[0].replace("%3A", ":")` — correct inverse.
- **No injection, no protocol downgrade.** Note: the function accepts `http://` URLs and
  generates `did:web:` DIDs from them.  Per spec, `did:web:` DIDs MUST resolve over HTTPS.
  The caller is responsible for supplying an `https://` URL; this is a design-level concern
  rather than an exploitable vulnerability.

### `detect.ts` — Clean

- **Protocol priority:** ROAR check (requires `roar` AND valid `intent`) is first, so a
  message with a valid ROAR `intent` but no `roar` field cannot be misidentified as ROAR.
  A2A check (`role` field) does not overlap ROAR because ROAR requires both fields.
- **ACP before MCP:** ACP is a JSON-RPC 2.0 subset; the prefix-based check correctly
  fires first.
- **`normalizeToROAR` field validation:** All raw field accesses use `?? default` fallbacks
  or `as Type` casts.  The resulting `ROARMessage` fields (`payload`, `context`, etc.) are
  passed to downstream handlers that tolerate arbitrary values.  No injection risk.
- **No JSON.parse** in this file (parsing is the caller's responsibility).

### `autonomy.ts` — Clean (FINAL-L1 noted above)

- **`tokenValid` / `tokenExpired`:** `expires_at <= 0` treated as no-expiry — correct.
- **`cleanup_expired` correctness:** Two-pass (collect then delete).  The `_by_grantee`
  splice is correct (`indexOf` + `splice`).
- **`randomBytes(8)` for token IDs:** Cryptographically random, appropriate entropy.
- **No Math.random for security purposes.**

### `discovery_cache.ts` — Clean

- **LRU implementation:** Map insertion-order is used correctly.  On get, delete+re-insert
  moves the entry to the back.  On evict, `Map.keys().next()` removes the front (oldest).
- **`_evict_expired` O(n):** Called only from `search()`, not from `put()`.  The `put()`
  path uses LRU eviction (O(1) amortized).  This is acceptable.
- **No unbounded collection growth:** `max_entries` is enforced on every `put`.

### `did_document.ts` — Clean

- **`publicKeyMultibase`:** Uses `f` prefix (lowercase hex per multibase spec).  This is a
  valid multibase encoding for a hex-encoded public key.
- **No secrets in `toDict()` output** — public key only.
- **No dynamic code execution.**

### `sqlite_directory.ts` — Clean (post-fix)

- **`path.resolve(dbPath)`** is applied before `mkdirSync` and `new DatabaseSync`.
  Path traversal is mitigated.
- **All SQL queries use parameterized `?` placeholders** — no SQL injection.
- **FINAL-L2** documented above (`_rowToEntry` unguarded `JSON.parse`).

---

## Re-Audit: Previously Reviewed Files

### `delegation.ts`

- `verifyAndValidateToken` is present and correct.  `verifyToken` is called first
  (short-circuit `&&`), so the more expensive validity check is skipped if the signature
  fails.  This is the correct evaluation order for both security and performance.
- Signing body excludes `signature` and `use_count` — correct.
- PREV-M2 (`consumeToken` non-atomic) remains documented.

### `router.ts`

- FINAL-M2 fixed (HTTP body cap).
- All previous High/Medium fixes confirmed present: `timingSafeEqual` for both auth paths,
  `trustProxy` flag, WS frame 64-bit validation, 1 MiB frame cap.

### `websocket.ts`

- 64-bit frame length high-word check present.
- 1 MiB frame cap present.
- Client frames masked with `crypto.randomBytes(4)`.

### `stdio.ts`

- 10 MiB cap present.

### `streaming.ts`

- AIMD logic: `_capacity` correctly floats between 1 and `maxBuffer`.
- `_replayBuffer` bounded by `replaySize`.
- `Subscription._buffer` bounded by `effectiveLimit`.
- No unbounded data structures.

### `dedup.ts`

- `_evict_expired` is O(n_expired) but breaks on first fresh entry (insertion-ordered Map).
- `_maxKeys` cap enforced in `mark_seen`.  Memory is bounded.

### `message.ts`

- `verifyMessage` uses `timingSafeEqual`.
- Canonical JSON body (`pythonJsonDumps`) correctly formats integers as `n.0` to match
  Python `json.dumps(sort_keys=True)`.

### `signing.ts`

- `generateEd25519KeyPair` uses `privRaw.slice(-32)` — correct for PKCS8 DER where the
  raw Ed25519 seed occupies the final 32 bytes.
- DER headers (`302e020100300506032b657004220420` / `302a300506032b6570032100`) are correct
  for PKCS8 and SPKI respectively.
- No private key material in error messages.

### `server.ts`

- FINAL-M1 fixed (HTTP body cap).
- Signature verification (`verifyMessage`) called when `signingSecret` is set.

### `client.ts`

- FINAL-L3 documented (unbounded response body).
- `config.secret` used only as an in-memory `Authorization` header value — not logged.

### `types.ts`

- `messageFromWire` performs no field validation (trusts caller to have parsed valid data).
  Downstream handlers receive `undefined` for missing fields; all callers wrap in try/catch.
- `randomHex` uses `randomBytes` — cryptographically secure.

---

## Cryptographic Checklist

| Check | Result |
|-------|--------|
| No `Math.random()` for security | Pass — all randomness via `crypto.randomBytes` |
| Timing-safe comparisons for secrets | Pass — `timingSafeEqual` in `message.ts`, `router.ts` |
| Key material absent from error messages | Pass — all `catch` blocks return `false` or rethrow opaque errors |
| Ed25519 raw key byte count enforced | Pass — `didKeyToPublicKey` enforces 32 bytes; `publicKeyFromHex` DER wrapping correct |
| Multicodec prefix `[0xed, 0x01]` order | Pass — matches W3C DID Key spec |
| base58btc alphabet | Pass — Bitcoin alphabet used correctly |
| HMAC canonical JSON matches Python | Pass — `pythonJsonDumps` integer `.0` format confirmed |
| Ed25519 signing uses `null` algorithm | Pass — `cryptoSign(null, ...)` / `cryptoVerify(null, ...)` |
| WS client frames masked | Pass — `crypto.randomBytes(4)` per RFC 6455 §5.1 |
| WS server frames unmasked | Pass — correct per RFC 6455 §5.1 |
| WS SHA-1 handshake accept key | Pass — GUID `258EAFA5-E914-47DA-95CA-C5AB0DC85B11` correct |
| SQL injection | Pass — all queries use parameterized placeholders |
| Dynamic code execution (`eval`, `Function`) | Pass — none found |
| Shell injection (`child_process`) | Pass — no `child_process` usage |

---

## Final Verdict

No Critical findings.  No new High findings.  Two Medium findings fixed in this commit
(HTTP POST body exhaustion in `server.ts` and `router.ts`).  Remaining Low findings are
documented above with recommended fixes and do not represent immediately exploitable
vulnerabilities in normal deployment.

The SDK is suitable for continued development and controlled testing.  Before production
use, the Low findings above (especially FINAL-L2 and FINAL-L1) should be addressed.
