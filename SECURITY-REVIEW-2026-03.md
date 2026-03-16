# ROAR Protocol Security Review (Protocol-Level)

Date: 2026-03-16
Scope: protocol spec (`ROAR-SPEC.md`, `spec/*.md`, schemas), SDK code (`python/src/roar_sdk`, `ts/src`), conformance tests (`tests/*`).

## Risk Summary by Severity

## Critical
1. **No mandatory replay cache at verifier boundary**  
   Signatures validate message integrity, but receivers can accept the same signed message repeatedly within timestamp window unless they separately enforce deduplication.

2. **Confused deputy via missing recipient binding policy**  
   Verification does not require `to.did` to match local service identity; valid signed messages can be forwarded to unintended recipients.

## High
1. **Trust establishment ambiguity for Ed25519 key source**  
   Message-level `auth.public_key` exists in SDK signer path, but trust source requirements are not normative. Implementers may trust attacker-supplied keys.

2. **Timestamp handling ambiguity (age vs future-skew)**  
   Existing verification uses absolute delta; spec does not normatively state maximum future skew nor mandatory rejection behavior.

3. **Downgrade/algorithm confusion risk**  
   Spec references HMAC and Ed25519 but lacks strict per-deployment allowlist language and unknown-scheme rejection rules.

## Medium
1. **Canonicalization under-specified across docs**  
   `ROAR-SPEC.md` canonical body differs from simplified `spec/04-exchange.md` example, creating interop and security drift risk.

2. **Schema validation gap at transport boundary**  
   TS parser validates only selected fields and may permit malformed nested identities/context shapes before business logic.

3. **Discovery poisoning exposure**  
   Discovery records/cards have no signed-attestation requirement and no trust tiering guidance.

4. **Message ordering not normatively defined**  
   No sequence semantics for multi-part workflows; implementations may process out of intended order.

## Code/Spec Mismatches

- `ROAR-SPEC.md` signing body includes `from`, `to`, `context`, and `auth.timestamp`, while `spec/04-exchange.md` shows a reduced body (`id`, `intent`, `payload`) in the signing snippet.
- Spec text mentions replay protection window but does not require a nonce/message-id dedup cache at receiver.
- Ed25519 usage exists in SDKs, but normative trust-binding to DID documents/directories is not explicit in exchange-layer verification requirements.

## Normative Wording Improvements Applied

Added to `spec/04-exchange.md`:
- Mandatory signature scheme allowlist and rejection of unknown schemes.
- Mandatory recipient DID binding.
- Mandatory timestamp presence + max-age + max-future-skew behavior.
- Mandatory replay cache keyed by message `id` for at least replay window.
- Mandatory canonical body parity and fail-closed behavior.
- Explicit key trust binding requirement (trusted DID/doc source, not message-only key).

## Conformance and Negative Test Recommendations

- Add mandatory negative tests for:
  - replay duplicate rejection
  - recipient mismatch rejection
  - future timestamp rejection
  - signature tampering rejection
- Maintain an interop matrix for Python↔TS and HMAC↔Ed25519 with pass/fail expectations for both positive and negative vectors.

## Reference Verifier Patch

Included a Python reference implementation (`StrictMessageVerifier`) that enforces:
- scheme allowlist
- recipient binding
- timestamp age + future skew
- replay cache via `IdempotencyGuard`
- fail-closed verification result with explicit error codes

This is intended as a secure baseline for production receivers and as a target for conformance parity in other SDKs.
