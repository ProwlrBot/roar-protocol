# ROAR Protocol — Compliance Matrix

**Version:** 0.3.0
**Date:** 2026-03-17

This matrix maps ROAR Protocol features to requirements across four compliance frameworks: SOC 2 Type II, GDPR, HIPAA, and ISO 27001:2022.

---

## Feature-to-Framework Mapping

| ROAR Feature | SOC 2 | GDPR | HIPAA | ISO 27001 |
|:------------|:------|:-----|:------|:----------|
| **Authentication** | | | | |
| DID-based agent identity | CC6.2 — Prior to issuing system credentials, the identity of the individual is verified | Art. 25 — Data protection by design (pseudonymous identifiers) | 164.312(d) — Person or entity authentication | A.5.17 — Authentication information |
| Ed25519 asymmetric signing | CC6.1 — Logical access security; CC6.2 — Authentication mechanisms | Art. 32 — Security of processing (cryptographic measures) | 164.312(d) — Authentication; 164.312(c) — Integrity | A.8.24 — Use of cryptography |
| HMAC-SHA256 symmetric signing | CC6.1 — Logical access; PI1.1 — Processing integrity | Art. 32 — Security of processing | 164.312(c)(1) — Integrity controls | A.8.24 — Use of cryptography |
| `StrictMessageVerifier` | CC6.1 — Logical access enforcement | Art. 32 — Appropriate technical measures | 164.312(a)(1) — Access control | A.8.3 — Information access restriction |
| **Authorization** | | | | |
| Capability-based delegation | CC6.3 — Role-based access based on need | Art. 5(1)(f) — Integrity and confidentiality | 164.312(a)(1) — Access control; 164.502(b) — Minimum necessary | A.5.15 — Access control; A.5.18 — Access rights |
| Graduated autonomy (WATCH/GUIDE/DELEGATE/AUTONOMOUS) | CC6.3 — Restricts access to authorized functions | Art. 25 — Data protection by design | 164.312(a)(1) — Conditional access | A.8.3 — Information access restriction |
| `DelegationToken` cryptographic grants | CC6.1 — Logical access with cryptographic controls | Art. 32 — Pseudonymisation and encryption | 164.312(a)(2)(iv) — Encryption mechanism | A.8.24 — Use of cryptography |
| Recipient binding in verifier | CC6.1 — Restricts access to intended recipient | Art. 5(1)(f) — Confidentiality principle | 164.312(e)(1) — Transmission security | A.8.24 — Use of cryptography |
| **Encryption** | | | | |
| TLS required for HTTP/WebSocket | CC6.6 — Encryption of data in transit | Art. 32(1)(a) — Encryption of personal data | 164.312(e)(1) — Transmission security | A.8.24 — Use of cryptography |
| Canonical JSON signing (message integrity) | PI1.1 — Processing integrity; CC6.6 | Art. 32 — Integrity of processing | 164.312(c)(1) — Integrity mechanism | A.8.24 — Use of cryptography |
| No payload encryption at rest (by design) | C1.1 — Confidentiality (operator must add) | Art. 32 — Operator must implement if processing PII | 164.312(a)(2)(iv) — Operator must implement for PHI | A.8.24 — Operator responsibility |
| **Audit Logging** | | | | |
| `AuditLog` tamper-evident chain | CC7.2 — Detection of unauthorized changes; PI1.1 | Art. 5(2) — Accountability principle | 164.312(b) — Audit controls | A.8.15 — Logging; A.8.17 — Clock synchronization |
| Ed25519-signed audit entries | CC7.2 — Integrity of monitoring data | Art. 32 — Integrity controls | 164.312(b) — Audit controls; 164.312(c) — Integrity | A.8.15 — Logging |
| SHA-256 hash chain (prev_hash linkage) | CC7.2 — Tamper detection | Art. 32 — Technical measures for integrity | 164.312(c)(1) — Integrity mechanism | A.8.15 — Logging |
| `AuditLog.verify_chain()` | CC7.2 — System monitoring verification | Art. 5(2) — Demonstrable compliance | 164.312(b) — Audit controls | A.8.15 — Logging |
| JSONL export (`export_jsonl`) | CC7.2 — Evidence preservation | Art. 15 — Right of access (data export); Art. 20 — Data portability | 164.312(b) — Audit log retention | A.8.15 — Logging |
| Metadata-only logging (no payloads) | C1.1 — Confidentiality | Art. 5(1)(c) — Data minimization | 164.502(b) — Minimum necessary | A.8.11 — Data masking |
| `AuditLog.query()` by agent, time, intent | CC7.2 — Monitoring and review | Art. 15 — Right of access | 164.524 — Access of individuals to PHI | A.8.15 — Logging |
| **Access Control** | | | | |
| Agent registration (explicit opt-in) | CC6.2 — Registration requires identity proof | Art. 7 — Conditions for consent | 164.312(a)(2)(i) — Unique user identification | A.5.17 — Authentication information |
| Agent unregistration (directory removal) | CC6.5 — Account deprovisioning | Art. 17 — Right to erasure | 164.310(a)(2)(iv) — Maintenance records | A.5.18 — Access rights (revocation) |
| Bearer token auth for WebSocket/SSE | CC6.1 — Logical access | Art. 32 — Authentication measures | 164.312(d) — Authentication | A.8.5 — Secure authentication |
| Token-bucket rate limiting | A1.2 — Availability controls | Art. 32 — Availability and resilience | 164.308(a)(7) — Contingency plan | A.8.6 — Capacity management |
| **Data Retention** | | | | |
| In-memory by default (no persistence) | C1.1 — Data disposed after use | Art. 5(1)(e) — Storage limitation | 164.530(j) — Retention requirements | A.8.10 — Information deletion |
| Configurable SQLite persistence | CC6.1 — Operator-controlled storage | Art. 5(1)(e) — Defined retention period | 164.530(j) — 6-year minimum for policies | A.8.10 — Information deletion |
| Configurable Redis token store | CC6.1 — TTL-based expiration | Art. 5(1)(e) — Storage limitation | 164.312(a)(2)(iv) — Encryption | A.8.10 — Information deletion |
| Replay guard TTL (600 seconds) | CC7.2 — Temporal bounds on monitoring data | Art. 5(1)(e) — Proportionate retention | N/A | A.8.10 — Information deletion |
| **Data Residency** | | | | |
| Hub-local storage | CC6.7 — Data restricted to authorized locations | Art. 44-49 — International transfers | 164.308(b)(1) — Business associate contracts | A.5.23 — Information security for cloud services |
| Opt-in federation | CC6.7 — Cross-boundary data flow controls | Art. 46 — Appropriate safeguards for transfer | 164.308(b)(1) — BAA for federated parties | A.5.23 — Cloud services |
| No default cross-border transfer | CC6.7 — Restrictive defaults | Art. 44 — General principle for transfers | 164.308(b)(1) — No transfer without agreement | A.5.23 — Cloud services |

---

## Control Coverage Summary

### SOC 2 Trust Service Criteria

| Criterion | ROAR Controls |
|:----------|:-------------|
| CC6.1 — Logical Access | DID identity, HMAC/Ed25519 signing, StrictMessageVerifier, DelegationToken, Bearer auth |
| CC6.2 — Authentication | DID-based identity, Ed25519 key pairs, agent registration |
| CC6.3 — Authorization | Capability-based delegation, graduated autonomy levels |
| CC6.5 — Account Lifecycle | Agent registration and unregistration |
| CC6.6 — Encryption in Transit | TLS for HTTP/WS, canonical JSON signing |
| CC6.7 — Data Boundaries | Hub-local storage, opt-in federation |
| CC7.1 — System Monitoring | EventBus streaming, StreamEvent types (monitor_alert, agent_status) |
| CC7.2 — Change Detection | AuditLog chain verification, replay detection, timestamp enforcement |
| CC8.1 — Change Management | Semantic versioning in VERSION.json |
| A1.2 — Availability | AIMD backpressure, rate limiting, configurable timeouts |
| PI1.1 — Processing Integrity | Message signing, audit chain verification |
| C1.1 — Confidentiality | TLS in transit, no default persistence, metadata-only audit |

### GDPR Articles

| Article | ROAR Controls |
|:--------|:-------------|
| Art. 5(1)(c) — Data Minimization | DIDs (no PII), metadata-only audit trail |
| Art. 5(1)(e) — Storage Limitation | In-memory defaults, configurable retention |
| Art. 5(1)(f) — Integrity/Confidentiality | HMAC/Ed25519 signing, TLS, recipient binding |
| Art. 5(2) — Accountability | Tamper-evident audit trail with cryptographic proof |
| Art. 7 — Consent | Explicit agent registration |
| Art. 15 — Right of Access | AuditLog.query() by agent DID |
| Art. 17 — Right to Erasure | Agent unregistration, directory removal |
| Art. 20 — Data Portability | JSONL export |
| Art. 25 — Privacy by Design | Pseudonymous DIDs, in-memory defaults, no PII collection |
| Art. 32 — Security of Processing | Cryptographic signing, TLS, access controls |
| Art. 44-49 — International Transfers | Hub-local default, opt-in federation |

### HIPAA Security Rule

| Section | ROAR Controls |
|:--------|:-------------|
| 164.308(a)(7) — Contingency Plan | Rate limiting, AIMD backpressure |
| 164.308(b)(1) — Business Associates | Federation requires explicit configuration (supports BAA workflow) |
| 164.312(a)(1) — Access Control | DID identity, capability delegation, StrictMessageVerifier |
| 164.312(b) — Audit Controls | AuditLog with chain verification and JSONL export |
| 164.312(c)(1) — Integrity | HMAC/Ed25519 signing, audit chain hashing |
| 164.312(d) — Authentication | DID-based identity, Ed25519 key pairs |
| 164.312(e)(1) — Transmission Security | TLS for HTTP/WS transports |
| 164.502(b) — Minimum Necessary | Metadata-only audit, capability-scoped delegation |

### ISO 27001:2022 Controls

| Control | ROAR Controls |
|:--------|:-------------|
| A.5.15 — Access Control | Capability-based delegation, graduated autonomy |
| A.5.17 — Authentication Information | DID-based identity, Ed25519 key pairs |
| A.5.18 — Access Rights | Agent registration/unregistration, DelegationToken |
| A.5.23 — Cloud Services | Hub-local storage, opt-in federation |
| A.8.3 — Information Access Restriction | StrictMessageVerifier, recipient binding, capability scoping |
| A.8.5 — Secure Authentication | HMAC/Ed25519, Bearer tokens |
| A.8.6 — Capacity Management | Token-bucket rate limiting, AIMD backpressure |
| A.8.10 — Information Deletion | In-memory defaults, configurable retention, agent unregistration |
| A.8.11 — Data Masking | Metadata-only audit (payloads excluded) |
| A.8.15 — Logging | AuditLog with tamper-evident chain, JSONL export, query API |
| A.8.17 — Clock Synchronization | Timestamp validation in StrictMessageVerifier (300s window, 30s future skew) |
| A.8.24 — Use of Cryptography | HMAC-SHA256, Ed25519, SHA-256 hash chains, TLS |

---

## Gaps and Operator Responsibilities

The following compliance requirements are **not addressed by ROAR itself** and must be implemented by the operator:

| Requirement | Framework(s) | Operator Action |
|:-----------|:------------|:---------------|
| Payload encryption at rest | HIPAA 164.312(a)(2)(iv), GDPR Art. 32 | Implement application-layer encryption for sensitive payloads |
| Retention period enforcement | HIPAA 164.530(j), GDPR Art. 5(1)(e), ISO A.8.10 | Configure automated deletion schedules for persistent backends |
| Breach notification | GDPR Art. 33-34, HIPAA 164.408 | Implement notification procedures and incident response plans |
| Data Protection Impact Assessment | GDPR Art. 35 | Conduct DPIA for high-risk processing of personal data in payloads |
| Business Associate Agreements | HIPAA 164.308(b)(1) | Execute BAAs before federating with external organizations |
| Security awareness training | SOC 2 CC1.4, HIPAA 164.308(a)(5), ISO A.6.3 | Train operators on ROAR security configuration |
| Physical security | SOC 2 CC6.4, HIPAA 164.310, ISO A.7 | Secure infrastructure hosting ROAR deployments |
| Backup and recovery | SOC 2 A1.2, HIPAA 164.308(a)(7), ISO A.8.13 | Implement backup procedures for persistent audit logs and directories |
