# ROAR Security Interoperability Matrix

| Sender SDK | Receiver SDK | Signature | Canonical fixture | Negative tamper | Replay duplicate | Future timestamp | Recipient mismatch |
|---|---|---|---|---|---|---|---|
| Python | Python | HMAC | MUST pass | MUST fail | MUST fail | MUST fail | MUST fail |
| TypeScript | TypeScript | HMAC | MUST pass | MUST fail | MUST fail | MUST fail | MUST fail |
| Python | TypeScript | HMAC | MUST pass | MUST fail | MUST fail | MUST fail | MUST fail |
| TypeScript | Python | HMAC | MUST pass | MUST fail | MUST fail | MUST fail | MUST fail |
| Python | Python | Ed25519 | MUST pass | MUST fail | MUST fail | MUST fail | MUST fail |
| TypeScript | TypeScript | Ed25519 | MUST pass | MUST fail | MUST fail | MUST fail | MUST fail |
| Python | TypeScript | Ed25519 | MUST pass | MUST fail | MUST fail | MUST fail | MUST fail |
| TypeScript | Python | Ed25519 | MUST pass | MUST fail | MUST fail | MUST fail | MUST fail |

Notes:
- "Canonical fixture" means both sides reproduce the exact canonical signing body and signature test vectors.
- Negative tests are mandatory conformance gates for security-sensitive releases.
