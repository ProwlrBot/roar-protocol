# ROAR Protocol Governance

**Real-time Open Agent Runtime — Governance Model v0.1**

---

## Overview

ROAR is an open specification. This document defines how decisions are made,
how the spec evolves, how conformance is judged, and how the project relates
to external standards bodies.

---

## Roles

### Spec Author

[@kdairatchi](https://github.com/kdairatchi) is the original designer and
current spec author. The spec author:

- Has final say on all wire format decisions
- Merges spec-breaking changes (major version bumps)
- Manages the `spec/VERSION.json` file
- Represents ROAR in external standards discussions (AAIF, IETF, W3C)

### Maintainers

Maintainers review PRs, manage issues, and merge non-breaking changes. They
can merge:

- Clarifications and documentation fixes (patch)
- New optional fields or event types (minor)
- New SDK implementations or adapter ports

They **cannot** merge:

- Changes to wire format, required fields, or signing canonical body
- New required fields on existing types
- Major version bumps

### Contributors

Anyone can open issues and PRs. The bar for spec changes is higher than for
SDK changes — see the Spec Change issue template.

---

## Decision-Making Process

### Patch changes (`0.2.x`)

Merged by any maintainer after 1 review. No spec change committee needed.
Examples: doc fixes, clarifications, new examples, test additions.

### Minor changes (`0.x.0`)

Require:
1. Issue opened using the **Spec Change** template
2. 7-day comment period
3. No blocking objections from maintainers
4. Spec author approval

Examples: new optional field on `ROARMessage`, new `StreamEventType`, new
adapter, new transport type.

### Major changes (`x.0.0`)

Require:
1. RFC document (Markdown) committed to `rfcs/` directory
2. 30-day comment period
3. Reference implementation in at least two languages
4. Spec author approval
5. Passing conformance test suite for all existing SDKs

Examples: change to signing canonical body, rename core fields, remove
required fields, change DID method format.

---

## Versioning

The spec uses semantic versioning independently of SDK versions.

```
spec/VERSION.json  — spec version (e.g. "0.2.0")
python/pyproject.toml — SDK version (tracks spec but may diverge for SDK-only fixes)
ts/package.json    — SDK version (same policy)
```

A spec version bump requires updating `spec/VERSION.json` and adding an
entry to `CHANGELOG.md` with a summary of changes.

The **wire format version** is encoded in every message as `"roar": "1.0"`.
This is independent of spec version — it only bumps on breaking wire changes.

---

## Conformance

An SDK is "ROAR-compliant" if and only if it passes all golden fixtures in
`tests/conformance/golden/`:

| Fixture | What it tests |
|:--------|:-------------|
| `identity.json` | AgentIdentity parsing, DID format, round-trip serialization |
| `message.json` | ROARMessage field names, intent enum values, wire format |
| `stream-event.json` | StreamEvent type enum values |
| `signature.json` | HMAC-SHA256 canonical body reproduction |

New SDKs must add a conformance runner before claiming compliance. The
conformance runner must be executable without a running server (offline,
deterministic, no randomness).

### Compliance badge

SDKs that pass conformance may use:
> `ROAR Protocol compliant — v0.2.0`

---

## External Standards Alignment

### Agentic AI Foundation (AAIF) — Linux Foundation

AAIF governs MCP, A2A, and related agentic protocols. ROAR aligns with AAIF
principles (open spec, conformance testing, multi-implementation). The goal
is eventual AAIF recognition as a **bridge protocol** between AAIF member
protocols.

- AAIF Technical Committee: `github.com/aaif/technical-committee`
- AAIF membership: `https://agenticai.foundation`

### W3C Decentralized Identifiers

ROAR's Layer 1 identity system (DIDs) is directly derived from W3C DID Core
v1.0. ROAR uses the `did:roar:` custom DID method, `did:key:` (W3C CCG), and
`did:web:` (W3C CCG). Any change to the DID format in ROAR must remain
consistent with W3C DID Core.

- W3C DID Core v1.0: `https://www.w3.org/TR/did-core/`
- did:key: `https://w3c-ccg.github.io/did-method-key/`
- did:web: `https://w3c-ccg.github.io/did-method-web/`

### IETF

ROAR's transport layer (Layer 3) uses standard IETF protocols:
- HTTP/1.1, HTTP/2 (RFC 7230, RFC 7540)
- WebSocket (RFC 6455)
- Server-Sent Events (W3C Living Standard, WHATWG)

ROAR's HMAC-SHA256 signing follows RFC 2104 (HMAC) and FIPS 180-4 (SHA-256).
ROAR's Ed25519 follows RFC 8032 and NIST FIPS 186-5.

IETF BANDAID (DNS-based agent discovery) is tracked as a future Layer 2
enhancement: `https://datatracker.ietf.org/doc/draft-mozleywilliams-dnsop-dnsaid/`

---

## Security Policy

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

The security-relevant components of the spec are:
1. The HMAC-SHA256 signing canonical body (Layer 4)
2. The Ed25519 key format and signing algorithm (Layer 1)
3. The DID format and trust chain (Layer 1)
4. Replay protection (timestamp window, Layer 4)
5. The delegation token signing body (Layer 1)

Changes to any of these require a major version bump and external security review.

---

## RFC Process

For major changes, open a PR adding a file at:

```
rfcs/NNNN-short-title.md
```

RFC template:

```markdown
# RFC NNNN: Short Title

**Status:** Draft | Review | Accepted | Rejected
**Author:** @github-handle
**Spec version:** 0.x.0 → 0.y.0 (or 1.0.0 if breaking)

## Summary
One paragraph.

## Motivation
Why is this needed? What problem does it solve?

## Specification
Exact wire format changes, field definitions, examples.

## Compatibility
What breaks? How do existing implementations migrate?

## Reference Implementation
Link to a branch with a working implementation.

## Alternatives Considered
What else was considered and why rejected.
```

---

## Relationship to ProwlrBot

[ProwlrBot](https://github.com/ProwlrBot/prowlrbot) is the reference
implementation of ROAR. It is maintained by the same author and tracks the
spec closely. However:

- ProwlrBot may add features not in the ROAR spec (platform-specific concerns)
- The ROAR spec is the authority on wire format, not ProwlrBot
- Other implementations (third-party agents, SDKs) are equally valid if
  they pass the conformance suite

The ProwlrBot SDK (`prowlrbot.protocols.sdk`) and the standalone
`roar-sdk` Python package should maintain feature parity. The audit table is
in [SDK-ROADMAP.md](SDK-ROADMAP.md).

---

## Code of Conduct

This project follows the Contributor Covenant v2.1.
`https://www.contributor-covenant.org/version/2/1/code_of_conduct/`
