# Security Policy

## Reporting Vulnerabilities

If you discover a security vulnerability in the ROAR Protocol specification or its reference SDKs, please report it responsibly — do **not** open a public GitHub issue.

**How to report:**

1. Go to the [GitHub Security Advisories page](https://github.com/kdairatchi/roar-protocol/security/advisories/new) for this repository
2. Click "Report a vulnerability"
3. Include:
   - A clear description of the vulnerability
   - Steps to reproduce
   - Affected component(s): spec, Python SDK, TypeScript SDK
   - Severity estimate (CVSS score if available)
   - Any suggested mitigations

We will acknowledge your report and keep you informed throughout the process.

---

## Scope

This policy covers the **roar-protocol** repository, which includes:

| Component | In scope |
|-----------|----------|
| Protocol specification (`spec/`) | Yes — logic errors, authentication bypass in the signing model |
| Python SDK (`python/`) | Yes — signature verification, HMAC replay protection, delegation token logic |
| TypeScript SDK (`ts/`) | Yes — signature verification, HMAC replay protection |
| Conformance tests (`tests/`) | Yes — incorrect golden fixtures could hide real vulnerabilities |
| Example code (`examples/`) | Informational — not production hardened, but report obvious flaws |

**Out of scope:**

- Vulnerabilities in third-party dependencies (report upstream)
- Bugs in systems built *on top of* ROAR Protocol

---

## Response Timeline

| Stage | Target |
|-------|--------|
| Acknowledgment | Within 48 hours |
| Triage | Within 72 hours |
| Critical patches | Within 7 days |
| Non-critical patches | Next planned release cycle |

---

## Safe Harbor / Responsible Disclosure

We support responsible disclosure. If you:

- Make a good-faith effort to avoid privacy violations, data destruction, or service disruption
- Report findings to us before any public disclosure
- Give us reasonable time to respond before disclosure

...then we will not pursue legal action against you for your research.

We ask that you do not publicly disclose the vulnerability until we have released a fix and given users reasonable time to update.

---

## Supported Versions

| Component | Supported versions |
|-----------|--------------------|
| Spec | 0.2.x (current) |
| Python SDK | 0.3.x (current) |
| TypeScript SDK | 0.3.x (current) |

Older versions do not receive security patches. Please upgrade to the current release.
