# Contributing to ROAR Protocol

Thanks for wanting to contribute. ROAR Protocol is an open specification with reference SDKs in Python and TypeScript. Here is how to get involved.

---

## Contents

- [Contributing to the Spec](#contributing-to-the-spec)
- [Contributing to the Python SDK](#contributing-to-the-python-sdk)
- [Contributing to the TypeScript SDK](#contributing-to-the-typescript-sdk)
- [Code Style](#code-style)
- [Commit Messages](#commit-messages)
- [Running Tests Locally](#running-tests-locally)
- [Running the Conformance Suite](#running-the-conformance-suite)
- [PR Requirements](#pr-requirements)

---

## Contributing to the Spec

The protocol specification lives in `spec/` and `ROAR-SPEC.md`. Changes to the spec require an RFC (Request for Comment) process:

1. Open an issue using the [Spec Change template](.github/ISSUE_TEMPLATE/spec_change.md)
2. Label it `proposal`
3. Discuss in the issue thread — aim for consensus before writing code
4. Once accepted, open a PR that includes:
   - Updated spec document(s) in `spec/`
   - Updated JSON Schema(s) in `spec/schemas/`
   - A `spec/VERSION.json` version bump
   - Updated conformance golden fixtures in `tests/conformance/golden/`
   - Links to corresponding SDK PRs so changes can be verified end-to-end

Spec changes without a prior RFC issue will not be merged.

---

## Contributing to the Python SDK

The Python SDK lives in `python/`. It is a standalone `roar-sdk` package with no external platform dependencies.

```bash
cd python
pip install -e ".[dev]"
pytest tests/ -v
```

- Source: `python/src/roar_sdk/`
- Tests: `python/tests/` and `tests/` (repo root, for conformance)
- Packaging: `python/pyproject.toml`

When adding a new module, also export it from `python/src/roar_sdk/__init__.py` and add it to `__all__`.

---

## Contributing to the TypeScript SDK

The TypeScript SDK lives in `ts/`. It targets Node.js >=18 and uses strict TypeScript.

```bash
cd ts
npm ci
npx tsc --noEmit   # type-check
```

- Source: `ts/src/`
- Build output: `ts/dist/` (generated, not committed)
- Package name: `@roar-protocol/sdk`

When adding exports, update `ts/src/index.ts`.

---

## Code Style

### Python

- Follow [PEP 8](https://peps.python.org/pep-0008/)
- All public functions and classes must have type hints
- Use [Pydantic](https://docs.pydantic.dev/) `BaseModel` for wire format types
- Docstrings for all public APIs

### TypeScript

- Strict TypeScript (`"strict": true` in tsconfig)
- No `any` types in public APIs
- ES modules (`.js` extensions in imports)
- `camelCase` for identifiers, `PascalCase` for types and interfaces

---

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `style`

Scopes: `spec`, `python`, `ts`, `ci`, `examples`, `tests`

Examples:
- `feat(spec): add graduated autonomy model to Layer 1`
- `fix(python): enforce DelegationToken max_uses server-side`
- `docs(ts): correct import paths in examples`
- `test(ci): add cross-SDK interop test`

---

## Running Tests Locally

### Python SDK unit tests

```bash
cd python
pip install -e ".[dev]"
pytest tests/ -v
```

### TypeScript type check

```bash
cd ts
npm ci
npx tsc --noEmit
```

### Version alignment check

```bash
python tests/check_versions.py
```

---

## Running the Conformance Suite

The conformance suite validates that the SDKs produce correct output for golden test fixtures in `tests/conformance/golden/`.

### Python conformance

```bash
# From repo root
pip install -e "./python[dev]"
pytest tests/conformance/ -v
```

### TypeScript conformance

```bash
# From repo root
node tests/validate_golden.mjs
```

---

## PR Requirements

- All CI checks must pass (see `.github/workflows/ci.yml`)
- New features must include tests
- Spec changes require a prior RFC issue (see above)
- Public APIs must be documented with docstrings / JSDoc
- Do not bump versions manually — version bumps are handled during release

---

## Questions?

Open a [GitHub Discussion](https://github.com/kdairatchi/roar-protocol/discussions) or file an issue.
