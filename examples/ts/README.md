# ROAR TypeScript Examples

> **Status: Pending SDK alignment.**

TypeScript examples will be added here once the TS SDK field names and enum values are aligned to the Python reference implementation.

See [SDK-ROADMAP.md](../../SDK-ROADMAP.md) — specifically the "Critical: Python / TypeScript Type Divergence" section — for the open tasks.

---

## What Will Go Here

Mirror of the Python examples:

- `echo_server.ts` — minimal ROAR server using Node.js / Bun
- `client.ts` — ROARClient sending a DELEGATE to the echo server or ProwlrBot

---

## Help Wanted

If you want to contribute the TypeScript examples:

1. Align `MessageIntent`, `AgentIdentity`, `ROARMessage`, `StreamEventType` in the TS SDK to match the canonical Python types (see SDK-ROADMAP.md)
2. Implement HTTP transport in the TS SDK
3. Write `echo_server.ts` and `client.ts` following the same pattern as the Python examples
4. Verify the golden signature fixture: `tests/conformance/golden/signature.json` must produce the same HMAC value in TypeScript

Open a PR and reference this file — we'll merge it.
