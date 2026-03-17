# ROAR Protocol Compatibility Matrix

## Spec ↔ SDK Version Mapping

| Spec Version | Python SDK | TypeScript SDK | Date | Notes |
|:------------|:-----------|:---------------|:-----|:------|
| 0.3.0 | 0.3.2 | 0.3.2 | 2026-03-17 | Full feature parity: RedisTokenStore, AgentCard attestation, StrictMessageVerifier, ROARHub federation |
| 0.2.0 | 0.2.0 | 0.2.0 | 2026-03-12 | Initial public spec: 5-layer model, 7 intents, HMAC-SHA256 signing |

## Feature Coverage by SDK

| Feature | Python | TypeScript | Since Spec |
|:--------|:-------|:-----------|:-----------|
| Layer 1: Identity (DID) | Complete | Complete | 0.2.0 |
| Layer 2: Discovery (Hub + Federation) | Complete | Complete | 0.2.0 |
| Layer 3: Connect (HTTP, WS, stdio) | Complete | Complete | 0.2.0 |
| Layer 4: Exchange (7 intents, signing) | Complete | Complete | 0.2.0 |
| Layer 5: Stream (EventBus, SSE) | Complete | Complete | 0.2.0 |
| Ed25519 Signing | Complete | Complete | 0.3.0 |
| AgentCard Attestation | Complete | Complete | 0.3.0 |
| StrictMessageVerifier | Complete | Complete | 0.3.0 |
| RedisTokenStore | Complete | Complete | 0.3.0 |
| ROARHub (full federation) | Complete | Complete | 0.3.0 |
| Challenge-Response Auth | Complete | Complete | 0.3.0 |
| Delegation Tokens | Complete | Complete | 0.3.0 |
| Protocol Auto-Detection | Complete | Partial | 0.3.0 |

## Bridge Protocol Support

| Bridge | Status | Spec Version |
|:-------|:-------|:-------------|
| MCP | Supported | 0.2.0+ |
| A2A | Supported | 0.2.0+ |
| ACP | Not yet | — |

## Conformance

Both SDKs pass **30/30** conformance checks against golden fixtures.
