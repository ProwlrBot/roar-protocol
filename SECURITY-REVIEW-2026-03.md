# ROAR Protocol Security Review (Protocol-Level)

Date: 2026-03-16  
Scope reviewed: protocol spec (`ROAR-SPEC.md`, `spec/*.md`, `spec/schemas/*.json`), SDK code (`python/src/roar_sdk`, `ts/src`), conformance and security tests (`tests/*`).

## 1) Protocol Risks by Severity

### Critical

1. **Replay window can be bypassed without mandatory dedup state**
   - Impact: an attacker can re-send a valid message multiple times within time window and trigger repeated side effects.
   - Evidence: base `verify()` in both SDKs checks signature+timestamp only; dedup is optional unless `StrictMessageVerifier` is used.
   - Recommendation: make receiver-side replay cache (`id` key) a hard requirement in all production profiles.

2. **Recipient confusion / confused deputy if `to.did` not bound**
   - Impact: signed messages intended for service A can be replayed/forwarded to service B if B validates only signature.
   - Evidence: strict verifier enforces recipient DID, but generic verifier APIs do not.
   - Recommendation: require policy check that `to.did` equals local receiver DID (or explicit alias set).

### High

1. **Canonicalization ambiguity across spec sections**
   - Impact: signature verification failures or, worse, inconsistent covered fields across implementations.
   - Evidence: prior `spec/04-exchange.md` signing snippet omitted `from`, `to`, `context`, `timestamp` while main spec and SDKs include them.
   - Remediation patch: updated `spec/04-exchange.md` signing body and normative canonicalization text.

2. **Trust-establishment ambiguity for Ed25519 key source**
   - Impact: implementations might trust a key supplied by attacker in message body (`auth.public_key`) and accept forged sender identity.
   - Evidence: signers include `auth.public_key`; only strict normative text says key must come from trusted DID/doc directory.
   - Recommendation: elevate this to explicit MUST-level verifier guidance in identity + exchange sections.

3. **Downgrade/algorithm confusion risk**
   - Impact: accepting unknown signature scheme, wrong major version, or fallback behavior can create verification bypass paths.
   - Evidence: mitigated in strict verifier and normative profile, but not uniformly asserted by parser-level validation.
   - Recommendation: require explicit allowlist + unknown-major-version rejection as conformance gate.

### Medium

1. **Timestamp validation semantics differ by API surface**
   - Generic verifiers use absolute delta (past/future symmetric), strict verifier uses max age + future skew.
   - This can produce inconsistent accept/reject behavior across deployments.

2. **Schema/validation gaps at runtime boundary**
   - TS `messageFromWire` validates only selected fields and leaves deep object validation to callers.
   - This can permit malformed nested identities/contexts into business handlers if schema validation is skipped.

3. **Discovery poisoning risks under-specified**
   - Discovery records are mutable and trust tiering/signature provenance is not fully normed.
   - Federation path needs signed provenance/TTL/revocation requirements.

4. **Message ordering semantics not normative**
   - No protocol-level sequence constraints for workflows where ordering matters.
   - Can cause race, stale update acceptance, and response confusion.

## 2) Code/Spec Mismatches

1. **Signing body mismatch (fixed in this patch)**
   - `spec/04-exchange.md` previously showed reduced HMAC body vs SDK and root spec full body.
   - Now aligned with SDK behavior.

2. **Schema vs implementation mismatch for Ed25519 auth fields**
   - Signers add `auth.public_key` for Ed25519.
   - `spec/schemas/roar-message.json` only permits `signature` and `timestamp` (`additionalProperties: false`).
   - This is an interoperability mismatch: Ed25519-signed messages with `public_key` violate schema.

3. **Normative profile stricter than baseline helpers**
   - Strict verifier enforces replay cache/recipient binding/future skew.
   - Basic `verify()` helpers do not enforce all of these, so teams may inadvertently run a weaker profile.

## 3) Exact Spec Wording Improvements

Applied in `spec/04-exchange.md`:

- Canonical body now explicitly includes:
  - `id`, `from.did`, `to.did`, `intent`, `payload`, `context`, `auth.timestamp`.
- Added normative deterministic canonicalization requirements:
  - recursive key ordering,
  - canonical numeric rendering,
  - exact field coverage,
  - golden-fixture validation recommendation.

Additional wording recommended (not yet patched):

1. **Schema/Ed25519 reconciliation**
   > "Receivers **MUST NOT** trust `auth.public_key` unless independently bound to sender DID in a trusted identity record. If `auth.public_key` is present and mismatches trusted key material, message **MUST** be rejected."

2. **Discovery trust tiering**
   > "Federated discovery entries **MUST** carry signed provenance (origin DID + signature over card + timestamps). Unsigned third-party entries **MUST** be treated as untrusted hints and **MUST NOT** authorize privileged actions."

3. **Ordering semantics for correlated flows**
   > "For multi-message workflows, sender **SHOULD** include monotonic `context.sequence` and receiver **MUST** reject stale or duplicate sequence values within a session when ordering is required by intent semantics."

4. **Version downgrade protection**
   > "Receivers **MUST** reject unknown major protocol versions. Receivers **MUST NOT** silently reinterpret unsupported versions as `1.0`."

## 4) Conformance & Negative Tests

### Added in this patch
- Expanded `tests/check_strict_verifier.py` with negative invariants for:
  - unsupported signature scheme rejection,
  - missing `auth.timestamp` rejection.

### Recommended next additions
- Cross-SDK matrix runner that executes all positive/negative vectors in both directions:
  - Python signer → TS verifier; TS signer → Python verifier,
  - HMAC and Ed25519.
- Dedicated downgrade vectors:
  - unknown signature scheme,
  - unknown major `roar` version,
  - omitted `auth.timestamp`,
  - mismatched `to.did`.
- Schema-negative fixture set:
  - extra top-level fields,
  - malformed nested `from`/`to`,
  - auth object with forbidden/ambiguous keys.

## 5) Reference Verifier Guidance

`StrictMessageVerifier` is a strong baseline policy gate. Teams should place it at transport ingress and only dispatch messages to intent handlers when `VerificationResult.ok == True`.

Minimum production profile:
- fixed scheme allowlist,
- receiver DID binding,
- max age + future skew check,
- replay cache with TTL >= replay window,
- trusted key resolution via DID/doc/directory.
