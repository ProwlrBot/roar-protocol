# Changelog

All notable changes to the ROAR Protocol specification are documented here.

Format: `[spec_version] — date — description`

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
- `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` (Apache 2.0)
- `spec/VERSION.json` with spec v0.1.0 declaration
- CI workflow (`.github/workflows/ci.yml`)
