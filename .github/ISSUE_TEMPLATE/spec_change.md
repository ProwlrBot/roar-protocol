---
name: Spec Change Proposal
about: Propose a change to the ROAR Protocol specification
title: "[SPEC] "
labels: proposal
assignees: ''
---

## Summary

<!-- One sentence describing what you want to change. -->

## Motivation

<!-- Why does the spec need this change? What real-world problem does it solve? Be specific — a concrete use case is worth more than a theoretical argument. -->

## Proposed Change

<!-- Describe the change in spec terms: what fields are added/removed/renamed, what enum values change, what wire format changes. Include a before/after if applicable. -->

**Before:**
```json

```

**After:**
```json

```

## Impact on Existing SDKs

<!-- Which SDKs break? What's the migration path? -->

| SDK | Impact | Migration |
|:----|:-------|:----------|
| Python (roar-sdk) | | |
| TypeScript | | |

## Impact on Existing Implementations

<!-- Will this break any deployed ROAR implementations? Will it break golden conformance fixtures? -->

- [ ] Breaking change to wire format
- [ ] New optional field (backward compatible)
- [ ] New enum value (backward compatible if SDKs use open enums)
- [ ] Documentation/clarification only (no wire format change)

## JSON Schema Change

<!-- Paste the proposed update to the relevant schema in spec/schemas/. -->

```json

```

## Conformance Test

<!-- Describe or paste the golden fixture change needed for tests/conformance/golden/. -->

## References

<!-- Links to related issues, MCP/A2A spec pages, real implementations, or prior art. -->
