# Changelog

All notable changes to the ROAR Protocol specification and reference SDKs are documented here.

Format: `[version] — date — description`

---

## [Python SDK 0.3.2] — 2026-03-16

### Added

- `StrictMessageVerifier` — production-grade reference verifier enforcing scheme allowlist, recipient DID binding, directional timestamp checks (age + future skew), and replay detection via `IdempotencyGuard`
- `VerificationResult` dataclass with `ok: bool` and `error: str` fields
- `RedisTokenStore` — multi-worker safe delegation token store using Redis atomic INCR; safe across multiple uvicorn/gunicorn workers. Requires `pip install roar-sdk[redis]`.
- `sign_agent_card(card, private_key_hex)` — signs an `AgentCard` with Ed25519 and stores the signature on `card.attestation`. Mitigates hub discovery poisoning.
- `verify_agent_card(card)` — verifies `card.attestation` against the card's own public key.
- `attestation: Optional[str]` field on `AgentCard` (backwards compatible, `None` by default)

---

## [TypeScript SDK 0.3.2] — 2026-03-16

### Added

- `StrictMessageVerifier` — mirrors Python implementation; exported from `@roar-protocol/sdk`
- `VerificationResult` and `StrictMessageVerifierOptions` interfaces
- `tests/check_strict_verifier.mjs` — 8 invariant checks mirroring Python test
- `ROARHub` — full hub server with challenge-response registration and federation sync/export
- `ChallengeStore` — one-time nonce store (30s TTL, replay-safe) used by hub registration
- `RedisTokenStore` — multi-worker safe token store using `ioredis` (optional peer dep)
- `signAgentCard(card, privateKeyHex)` — Ed25519 attestation for `AgentCard`; mitigates hub discovery poisoning
- `verifyAgentCard(card)` — verifies `card.attestation` against the card's own public key
- `attestation?: string` field on `AgentCard` (backwards compatible, `undefined` by default)

---

## [Python SDK 0.3.0] — 2026-03-16

### Security (audit fixes)

- Enforce `DelegationToken.max_uses` server-side — tokens with exhausted use counts are now rejected at the server layer, not just flagged by `is_valid()`
- Timestamp replay window enforced strictly: messages older than 300 seconds are rejected
- Empty `auth: {}` field now causes the server to return 403 rather than silently passing

### Changed

- `__version__` aligned to `0.3.0` to match `pyproject.toml`
- Added `py.typed` marker (PEP 561) so mypy and pyright recognise inline type annotations

---

## [TypeScript SDK 0.3.0] — 2026-03-16

### Security (audit fixes, aligned with Python SDK 0.3.0)

- `verifyMessage` now enforces the 300-second replay window
- Package version bumped from `1.0.0` to `0.3.0` to match spec maturity and Python SDK

### Changed

- Import paths in examples changed from repo-relative paths to `@roar-protocol/sdk` package imports

---

## [Python SDK 0.2.1] — 2026-03-13

### Fixed

- Minor bug fixes in `ROARClient` HTTP error handling
- `AgentDirectory.search()` now returns an empty list (not `None`) when no agents match

---

## [Python SDK 0.2.0] — 2026-03-12

### Added

- Initial public release of standalone `roar-sdk` Python package
- `AgentIdentity`, `AgentCard`, `AgentDirectory`, `ROARMessage`, `MessageIntent`
- `ROARClient` (HTTP), `ROARServer` (FastAPI), `ROARHub`
- Ed25519 asymmetric signing (`roar_sdk.signing`)
- `DelegationToken`, `issue_token`, `verify_token`
- DID method support: `did:roar`, `did:key`, `did:web`
- `SQLiteAgentDirectory` for persistent discovery
- `DiscoveryCache`, `IdempotencyGuard`, `AutonomyLevel`
- MCP, A2A, and ACP protocol adapters

---

## [0.2.0] — 2026-03-12

### Added

- `ROAR-SPEC.md` — umbrella specification document linking all 5 layers
- `SDK-ROADMAP.md` — implementation status and open tasks for Python/TS SDKs
- `spec/schemas/` — JSON Schemas for `AgentIdentity`, `ROARMessage`, `StreamEvent`
- `examples/python/` — runnable echo server and client
- `tests/conformance/` — language-agnostic golden fixtures
- `.github/ISSUE_TEMPLATE/spec_change.md` — RFC template for spec proposals
- Scope section in README clarifying spec vs SDK
- "Where's the code?" section in README linking to both SDK implementations
- "Implement ROAR in 5 steps" quickstart in README
- Concrete scenario in README showing cross-layer message flow
- Security model section in README (HMAC vs Ed25519, end-to-end signing flow)
- HTTP endpoints table in ROAR-SPEC.md

### Changed

- README: Fixed incorrect intent names (`request/response/subscribe/unsubscribe/error/cancel` → `execute/delegate/update/ask/respond/notify/discover`)
- README: Added branding and origin story from [@kdairatchi](https://github.com/kdairatchi)
- `spec/VERSION.json`: Added `python_sdk_min_version` and `ts_sdk_min_version` fields

---

## [0.1.0] — 2026-03-11

### Added

- Initial spec: `spec/01-identity.md` through `spec/05-stream.md`
- `README.md` with 5-layer overview and comparison table
- `INSTALL.md` — ProwlrBot as reference implementation
- `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` (MIT)
- `spec/VERSION.json` with spec v0.1.0 declaration
- CI workflow (`.github/workflows/ci.yml`)
