# ROAR Conformance Tests

Language-agnostic tests that any ROAR-compliant SDK must pass.

---

## What "Conformance" Means

A ROAR-compliant SDK must:

1. **Parse** all golden fixtures without error
2. **Validate** field names and enum values match the spec exactly
3. **Round-trip** — serialize a parsed fixture back to JSON and get identical output
4. **Sign correctly** — reproduce the exact HMAC-SHA256 value in `signature.json`

If your SDK passes all four, it can interoperate with any other compliant SDK.

---

## Golden Fixtures

```
tests/conformance/golden/
├── identity.json       AgentIdentity — DID format, field names, enum values
├── message.json        ROARMessage — all 8 fields, intent enum, auth structure
├── stream-event.json   StreamEvent — type enum, source DID format
└── signature.json      HMAC-SHA256 canonical body + expected signature
```

---

## Running Python Conformance

Requires: `pip install -e ".[dev]"` from [prowlrbot](https://github.com/ProwlrBot/prowlrbot)

```bash
cd /path/to/roar-protocol
python -m pytest tests/ -v
```

Or run the fixture validator directly:

```bash
python3 tests/validate_golden.py
```

Expected output:

```
✅ identity.json    — parse OK, DID format OK, round-trip OK
✅ message.json     — parse OK, intent=delegate OK, auth OK
✅ stream-event.json — parse OK, type=task_update OK
✅ signature.json   — HMAC matches: hmac-sha256:aa0eabc3...
All 4 conformance tests passed.
```

---

## Running TypeScript Conformance

Requires Node.js 18+. No npm install needed — uses only Node built-ins.

```bash
node tests/validate_golden.mjs
```

Expected output:

```
identity.json    ✅
message.json     ✅
stream-event.json ✅
signature.json   ✅

All 22 conformance checks passed. ✅
```

The signature check verifies that the TypeScript `pythonJsonDumps` function produces
the same canonical JSON as Python's `json.dumps(sort_keys=True)`, including the
float-formatting rule (`1710000000` → `1710000000.0`).

---

## Adding Your SDK

If you build a ROAR SDK in another language:

1. Parse each fixture in `golden/`
2. Assert all field names and values match
3. For `signature.json`: reproduce `expected_signature` from `inputs` and `secret`
4. Open a PR adding your SDK's conformance test runner to this directory

---

## Adding New Golden Fixtures

When the spec adds a new type or changes wire format:

1. Generate the fixture deterministically (fixed timestamp, fixed DID)
2. Compute any signatures using the shared `roar-conformance-test-secret`
3. Add to `tests/conformance/golden/`
4. Bump `spec/VERSION.json`
5. Update all SDK conformance test runners


## Security Negative Tests

Run strict verification invariants (replay, recipient-binding, future timestamp, tamper):

```bash
python3 tests/check_strict_verifier.py
```

See `tests/interop-matrix.md` for required cross-SDK security outcomes.
