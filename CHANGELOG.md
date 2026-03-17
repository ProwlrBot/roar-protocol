# Changelog

All notable changes to the ROAR Protocol specification and reference SDKs are documented here.

Format: `[version] — date — description`

---

## [Cross-Terminal Release] — 2026-03-17

Coordinated release across all four engineering terminals.

### Security (Terminal 1)

- **SEC-001**: Atomic token enforcement via Redis Lua script — prevents counter overshoot that permanently blacklists legitimate tokens
- **SEC-002**: Removed same-party delegation fast path that trusted wire `public_key` — all delegation keys now resolved from trusted sources only (fail closed)
- **SEC-007**: Sanitized error messages in hub challenge/unregister endpoints — no longer leaks Pydantic schema details or ValueError internals
- **SEC-010**: Replaced string-prefix IP check with proper `ipaddress.ip_network` CIDR validation — `172.1.x.x` (public) no longer treated as trusted proxy
- **SEC-013**: Key rotation grace period capped by original key expiry — compromised short-TTL keys can no longer gain extra lifetime via rotation
- `KeyTrustStore` — Ed25519 key trust enforcement with automated rotation, grace periods, and mandatory expiration (Python + TypeScript parity)

### SDK (Terminal 2)

- **Go SDK**: Server (`go/server.go`) and Hub (`go/hub.go`) with HTTP handlers, replay protection, signature verification, and intent routing
- **Go SDK**: Fixed Content-Type header ordering in hub registration (set before `WriteHeader`)
- **Rust SDK**: Server (`rust/src/server.rs`) and Hub (`rust/src/hub.rs`) with `tiny_http`, serde integration, replay protection, and full test suites
- **TypeScript**: `KeyTrustStore` (`ts/src/key_trust.ts`) mirroring Python implementation with SEC-013 grace period cap
- **TypeScript**: stdio transport verified functional for local agent communication
- Plugin API (`plugin.py`), EventBridge (`event_bridge.py`), Identity Migration (`migration.py`)

### Infrastructure (Terminal 3)

- 76 new conformance tests across 5 files: edge cases, replay attacks, invalid signatures, delegation chains, unauthorized access
- Docker images: `Dockerfile.hub` and `Dockerfile.agent` — non-root, health checks, slim base
- `docker-compose.observability.yml` — full stack with Prometheus, Grafana, OTel collector, Redis, nginx
- Kubernetes manifests: namespace, configmap, hub/agent deployments (2 replicas each), Redis StatefulSet with PVC, NetworkPolicies
- Grafana dashboard: 8 panels (request rate, auth failures, latency P50/95/99, rate limits, error %, Redis health, message throughput, Redis memory)
- OTel collector config with OTLP receivers and Prometheus exporter
- Grafana datasource provisioning with explicit `uid: prometheus` for dashboard compatibility

### Developer Experience (Terminal 4)

- `docs/DIAGRAMS.md` — 12+ Mermaid diagrams covering architecture, message flow, signing, intents, discovery, federation, delegation, transport, streaming, DNS discovery, protocol bridge, connection lifecycle, and class diagrams
- `docs/DNS-DISCOVERY.md` — comprehensive guide for DNS-based agent discovery (DNS-AID/BANDAID, did:web, ANP, well-known) with zone file generation, security considerations, and setup instructions
- `docs/TUTORIALS.md` — 4 video tutorial scripts: Getting Started (12 min), Running a Hub (15 min), Using the SDKs (18 min), Security Basics (10 min)
- README: Spec badge updated v0.2.0 → v0.3.0, added DIAGRAMS.md link to spec table

### Cross-Terminal Audit Fixes

- DelegationToken diagram fields corrected (`delegator_did`/`delegate_did` instead of `issuer_did`/`subject_did`)
- StreamEventType count corrected to 11 (was 8 — added `stream_start`, `stream_end`, `agent_delegate`)
- Tutorial code examples fixed to match actual SDK API (correct method names, field names, import paths)
- OTel collector config: replaced deprecated `loglevel` with `verbosity`

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
