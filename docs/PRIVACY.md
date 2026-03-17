# ROAR Protocol — Privacy and Compliance Documentation

**Version:** 0.3.0
**Date:** 2026-03-17
**Status:** Active

---

## 1. Data Flow Overview

ROAR is a protocol specification and SDK for agent-to-agent communication. This section describes what data flows through a ROAR deployment, how it is processed, and where it is stored.

### 1.1 Data Collected

| Data Category | Description | Sensitivity |
|:-------------|:-----------|:-----------|
| Agent Identity (DID) | Decentralized Identifier, e.g. `did:roar:agent:planner-a1b2c3d4` | Low — no PII, algorithmically generated |
| Display Name | Human-readable agent label, e.g. "code-reviewer" | Low — describes function, not a person |
| Agent Capabilities | List of declared skills, e.g. `["python", "architecture"]` | Low — functional metadata |
| Public Key (Ed25519) | 32-byte public key hex for signature verification | Low — public by design |
| Message Payload | Intent-specific content (task descriptions, tool results) | Variable — depends on application |
| Message Context | Session IDs, trace IDs, delegation tokens | Low — operational metadata |
| Auth Metadata | HMAC-SHA256 or Ed25519 signatures, timestamps | Low — cryptographic artifacts |
| Audit Trail Entries | Sequence, timestamp, DIDs, intent, message hash, chain hash, signature | Low — metadata only, no payload content |

### 1.2 Data NOT Collected by ROAR

ROAR does not collect, require, or process:

- Personal names, email addresses, or phone numbers
- IP addresses (transport-layer concern, not protocol-layer)
- Browser fingerprints or device identifiers
- Location data
- Financial information
- Biometric data

### 1.3 Data Processing

ROAR processes data in the following ways:

1. **Signing:** Message fields (id, from DID, to DID, intent, payload, context, timestamp) are serialized to canonical JSON and signed with HMAC-SHA256 or Ed25519. The signing operation is deterministic and does not transmit data to external services.

2. **Verification:** Incoming messages are verified against the sender's shared secret (HMAC) or public key (Ed25519). Replay protection checks message age (300-second window) and deduplicates by message ID (600-second retention).

3. **Discovery:** Agent cards are registered in a directory (in-memory, SQLite, or federated hub). Discovery queries match on capabilities. No data leaves the hub unless federation is explicitly configured.

4. **Audit:** The audit module (`audit.py`) records metadata about message exchanges — sender DID, receiver DID, intent, message hash, and trace ID. It does NOT record message payloads. Each entry is chained via SHA-256 and signed with Ed25519.

### 1.4 Data Storage

| Component | Default Storage | Persistence |
|:----------|:---------------|:-----------|
| Agent Directory | In-memory dict | None — lost on process exit |
| Agent Directory (SQLite) | Local SQLite file | Persistent, operator-controlled |
| Message State | In-memory only | None — not persisted |
| Replay Guard (IdempotencyGuard) | In-memory LRU with TTL | None — 600-second window then evicted |
| Audit Log | In-memory list | None — unless explicitly exported to JSONL |
| Delegation Tokens | In-memory or Redis | Configurable by operator |

ROAR has no default persistence. All data is in-memory unless the operator explicitly configures a persistent backend (SQLite directory, Redis token store, JSONL audit export).

---

## 2. Agent Identity and Privacy

### 2.1 DID-Based Identity

ROAR agents identify themselves using W3C Decentralized Identifiers (DIDs). A DID is a cryptographically generated string that contains no personally identifiable information:

```
did:roar:agent:planner-a1b2c3d4e5f6g7h8
```

The DID encodes:
- A method prefix (`did:roar:`)
- An agent type (`agent`, `tool`, `human`, `ide`)
- A slug derived from the display name
- A random hex suffix

No registry, certificate authority, or identity provider is required. Agents can generate their own DIDs locally using `did:key:` (where the DID is the public key itself) for fully self-sovereign, zero-infrastructure identity.

### 2.2 No PII Required

Agent registration requires only:
- A display name (functional label, not a personal name)
- A capabilities list
- An optional public key

No email, no password, no OAuth token, no personal data of any kind.

### 2.3 Pseudonymity

Agents are pseudonymous by default. A DID like `did:roar:agent:reviewer-f5e6d7c8` reveals nothing about the human operator behind it. The mapping from DID to human identity (if any) is entirely outside ROAR's scope and under the operator's control.

---

## 3. Message Handling and Encryption

### 3.1 Message Signing

Every ROAR message is signed before transmission. The signature covers all security-relevant fields:

- Message ID
- Sender DID
- Receiver DID
- Intent
- Payload
- Context
- Timestamp

Two signing schemes are supported:
- **HMAC-SHA256:** Symmetric shared secret. Suitable for intra-organization communication.
- **Ed25519:** Asymmetric key pair. Suitable for cross-organization trust where shared secrets are impractical.

### 3.2 Content Encryption

**ROAR does not encrypt message content at rest.** Messages are signed for integrity and authenticity, but payload content is transmitted in cleartext within the transport channel.

Transport-layer encryption is required for production deployments:
- **HTTP:** TLS 1.2+ required
- **WebSocket:** WSS (TLS) required
- **stdio:** Local process communication, no network exposure
- **gRPC:** TLS required (Phase 3)

Operators requiring payload encryption at rest must implement it at the application layer above ROAR.

### 3.3 Replay Protection

The `StrictMessageVerifier` enforces:
- **Timestamp window:** Messages older than 300 seconds (5 minutes) are rejected
- **Future skew limit:** Messages more than 30 seconds in the future are rejected
- **ID deduplication:** The `IdempotencyGuard` tracks seen message IDs for 600 seconds and rejects duplicates
- **Recipient binding:** Messages addressed to a different DID are rejected

---

## 4. Audit Trail

### 4.1 Tamper-Evident Logging

The `AuditLog` class provides a cryptographic audit trail where each entry is:

1. **Hashed** (SHA-256) over its content fields (sequence, timestamp, sender DID, receiver DID, intent, message ID, message hash, trace ID, previous hash)
2. **Chained** to the previous entry via `prev_hash` (blockchain-style hash chain)
3. **Signed** with Ed25519 using the operator's private key

Any modification to any entry invalidates all subsequent entries in the chain.

### 4.2 What the Audit Trail Records

The audit trail records **metadata only**:

| Field | Description |
|:------|:-----------|
| `sequence` | Monotonically increasing entry number |
| `timestamp` | Unix timestamp of the audit record |
| `sender_did` | DID of the message sender |
| `receiver_did` | DID of the message receiver |
| `intent` | Message intent (execute, delegate, update, ask, respond, notify, discover) |
| `message_id` | Unique message identifier |
| `message_hash` | SHA-256 hash of the message's security-relevant fields |
| `trace_id` | Distributed tracing identifier |
| `prev_hash` | Hash of the previous audit entry (chain linkage) |
| `entry_hash` | SHA-256 hash of this entry's content fields |
| `signature` | Ed25519 signature over `entry_hash` |

The audit trail does **not** record message payloads, reducing the compliance surface area for sensitive data.

### 4.3 Verification and Export

- **Chain verification:** `AuditLog.verify_chain()` validates every entry's hash, chain linkage, and Ed25519 signature
- **Export:** `AuditLog.export_jsonl()` writes the log as newline-delimited JSON for external archival
- **Import:** `AuditLog.load_jsonl()` reconstitutes a log from JSONL for offline verification
- **Query:** `AuditLog.query()` filters entries by agent DID, time range, intent, with configurable limits
- **CLI:** `roar audit verify <file>` provides command-line chain verification

---

## 5. Data Retention

### 5.1 Default Behavior

ROAR has **no default data persistence**. All runtime state (agent directory, message state, replay guard, audit log) is held in-memory and lost when the process exits. This is a deliberate design choice: operators must explicitly opt into persistence.

### 5.2 Configurable Persistence

| Backend | Configuration | Retention |
|:--------|:-------------|:----------|
| In-memory directory | Default | Process lifetime |
| SQLite directory | `SQLiteAgentDirectory(path)` | Until operator deletes the file |
| Redis token store | `RedisTokenStore(url)` | Configurable TTL per token |
| JSONL audit export | `AuditLog.export_jsonl(path)` | Until operator deletes the file |

### 5.3 Operator Responsibilities

Operators who enable persistent storage are responsible for:
- Defining retention periods appropriate to their compliance requirements
- Implementing automated deletion or rotation schedules
- Securing persistent storage at rest (filesystem encryption, database encryption)
- Backing up audit logs before deletion if required by regulation

---

## 6. GDPR Compliance Mapping

The General Data Protection Regulation (EU 2016/679) applies when ROAR processes personal data of EU data subjects. The following mapping shows how ROAR's architecture supports GDPR compliance.

| GDPR Requirement | ROAR Implementation | Notes |
|:----------------|:-------------------|:------|
| **Lawful Basis (Art. 6)** | Operator-defined | ROAR does not determine lawful basis; operators must establish it for their use case |
| **Data Minimization (Art. 5(1)(c))** | DIDs contain no PII; audit trail records metadata only, not payloads | By design, ROAR collects the minimum data needed for agent communication |
| **Right to Erasure (Art. 17)** | Agent unregistration removes the agent from the directory | Operators must also purge any persistent storage (SQLite, Redis, JSONL exports) |
| **Right to Access (Art. 15)** | `AuditLog.query(agent_did=...)` retrieves all entries for a given agent | Operators can export results via JSONL |
| **Data Portability (Art. 20)** | JSONL export provides machine-readable audit data | Standard JSON format, no vendor lock-in |
| **Consent (Art. 7)** | Agent registration is an explicit, affirmative action | No implicit data collection; agents must call `register()` |
| **Privacy by Design (Art. 25)** | No PII in DIDs, no default persistence, in-memory by default | Privacy-protective defaults require no operator configuration |
| **Data Protection Impact Assessment (Art. 35)** | Operator responsibility | Required when ROAR processes high-risk personal data in payloads |
| **Cross-Border Transfer (Art. 44-49)** | Hub-local by default; federation is opt-in | No data leaves the deployment unless the operator explicitly configures federation |
| **Breach Notification (Art. 33-34)** | Tamper-evident audit trail supports forensic investigation | Operators must implement their own breach notification procedures |

### 6.1 GDPR-Specific Recommendations

1. **Conduct a DPIA** before deploying ROAR in contexts where message payloads contain personal data
2. **Configure retention policies** for all persistent backends
3. **Implement an agent unregistration workflow** that covers directory removal, audit log annotation, and persistent storage purge
4. **Document federation agreements** as data processing agreements (DPAs) under Art. 28 when federating across organizational boundaries

---

## 7. SOC 2 Compliance Mapping

SOC 2 Type II compliance requires controls across five Trust Service Criteria. The following mapping shows how ROAR's architecture supports each.

| SOC 2 Criterion | ROAR Implementation | Evidence |
|:----------------|:-------------------|:---------|
| **CC6.1 — Logical Access** | HMAC-SHA256 and Ed25519 message signing; `StrictMessageVerifier` enforces signature validation | `verifier.py`: signature scheme allowlisting, recipient binding |
| **CC6.2 — Authentication** | DID-based identity with cryptographic proof; Bearer token auth for WebSocket/SSE | `signing.py`: Ed25519 key pair generation and verification |
| **CC6.3 — Authorization** | Capability-based delegation with `CapabilityDelegation` and `DelegationToken`; graduated autonomy levels (WATCH, GUIDE, DELEGATE, AUTONOMOUS) | Spec Layer 1: graduated autonomy model |
| **CC6.6 — Encryption in Transit** | TLS required for HTTP and WebSocket; transport config enforced via `ConnectionConfig` | Spec Layer 3: transport requirements |
| **CC7.1 — System Monitoring** | Real-time event streaming via `EventBus`; `StreamEvent` types include `monitor_alert` and `agent_status` | Spec Layer 5: event types |
| **CC7.2 — Anomaly Detection** | Replay detection via `IdempotencyGuard`; timestamp skew detection; AIMD backpressure for rate anomalies | `verifier.py`: replay and future-skew checks |
| **CC8.1 — Change Management** | Semantic versioning in `spec/VERSION.json`; wire format changes tracked by version | `VERSION.json`: version tracking |
| **A1.2 — Availability** | AIMD backpressure prevents consumer overload; configurable timeouts in `ConnectionConfig` | Spec Layer 5: AIMD algorithm |
| **PI1.1 — Data Processing Integrity** | HMAC/Ed25519 signing ensures message integrity; audit chain hash verification detects tampering | `audit.py`: chain verification with `verify_chain()` |
| **C1.1 — Confidentiality** | TLS in transit; no default persistence at rest; message payloads not stored in audit trail | Architecture: in-memory-first design |

### 7.1 SOC 2 Audit Evidence

The following artifacts support SOC 2 audit evidence collection:

- **Audit logs:** Export via `AuditLog.export_jsonl()` with Ed25519 signatures proving log integrity
- **Configuration records:** `ConnectionConfig` documents transport and auth settings
- **Agent directory snapshots:** `AgentDirectory` state can be serialized for point-in-time records
- **Replay guard metrics:** `IdempotencyGuard` tracks duplicate detection events

---

## 8. HIPAA Compliance Considerations

The Health Insurance Portability and Accountability Act (HIPAA) applies when ROAR processes Protected Health Information (PHI).

### 8.1 HIPAA Requirements and ROAR

| HIPAA Requirement | ROAR Support | Gap / Operator Action |
|:-----------------|:-------------|:---------------------|
| **Business Associate Agreement (BAA)** | N/A — ROAR is a protocol, not a service | Operators deploying ROAR with PHI must execute BAAs with all parties in the communication chain |
| **Access Controls (164.312(a))** | DID-based identity, capability-based authorization, `StrictMessageVerifier` | Operators must configure appropriate access policies |
| **Audit Controls (164.312(b))** | `AuditLog` with tamper-evident chain and Ed25519 signatures | Operators must enable audit logging and configure retention per HIPAA's 6-year minimum |
| **Integrity Controls (164.312(c))** | HMAC-SHA256 and Ed25519 message signing; audit chain hash verification | Signing is built-in; operators must ensure it is enabled |
| **Transmission Security (164.312(e))** | TLS required for HTTP/WebSocket transports | Operators must enforce TLS configuration |
| **Encryption at Rest (164.312(a)(2)(iv))** | Not provided by ROAR | Operators must implement application-layer or storage-layer encryption for PHI |
| **Minimum Necessary (164.502(b))** | Audit trail records metadata only, not payloads; DIDs contain no PII | ROAR's data minimization supports this principle |

### 8.2 HIPAA-Specific Recommendations

1. **Execute BAAs** with all organizations participating in federated ROAR hubs that process PHI
2. **Enable audit logging** with JSONL export and configure 6-year retention
3. **Encrypt PHI payloads** at the application layer before passing them to ROAR messages
4. **Do not include PHI** in agent display names, capability lists, or other identity fields
5. **Restrict federation** to organizations covered by BAAs
6. **Conduct a HIPAA risk assessment** specific to the ROAR deployment

---

## 9. Data Residency

### 9.1 Hub-Local by Default

ROAR agent directories are local to the hub instance. An agent registered on a hub in Frankfurt stays in Frankfurt. No data crosses network boundaries unless the operator explicitly configures federation.

### 9.2 Federation Is Opt-In

`ROARHub` federation requires explicit configuration:
- The operator must configure federation peer URLs
- Sync is performed via `/roar/federation/sync` endpoints
- Each hub controls which agents it shares and accepts

### 9.3 Cross-Border Considerations

When federation spans jurisdictions:
- Operators must ensure compliance with data transfer regulations (GDPR Chapter V, PIPL Art. 38-43, etc.)
- Federation agreements should document data processing terms
- Operators may restrict federation to hubs within the same jurisdiction

### 9.4 Deployment Models

| Model | Data Residency | Federation |
|:------|:--------------|:-----------|
| Single hub, single region | All data in one jurisdiction | None |
| Single hub, multi-region | Determined by hub hosting location | None |
| Federated hubs, same jurisdiction | All data in one jurisdiction | Intra-jurisdiction sync |
| Federated hubs, cross-border | Data in multiple jurisdictions | Requires data transfer agreements |

---

## 10. Security Controls Summary

| Control | Implementation | Layer |
|:--------|:--------------|:------|
| Agent authentication | DID + Ed25519 / HMAC-SHA256 | Layer 1, Layer 4 |
| Message integrity | Canonical JSON signing | Layer 4 |
| Replay protection | Timestamp window + ID deduplication | Layer 4 |
| Recipient binding | `StrictMessageVerifier` DID check | Layer 4 |
| Transport encryption | TLS required for HTTP/WS | Layer 3 |
| Rate limiting | Token-bucket in FastAPI router | Layer 3 |
| Audit logging | Tamper-evident chain with Ed25519 | Cross-layer |
| Access control | Capability-based delegation, graduated autonomy | Layer 1 |
| Backpressure | AIMD congestion control | Layer 5 |
| Idempotency | LRU-bounded deduplication guard | Layer 5 |

---

## 11. Contact

For privacy or compliance questions regarding the ROAR Protocol specification, open an issue on the [GitHub repository](https://github.com/kdairatchi/roar-protocol) or contact the maintainers through the channels listed in the repository.

For security vulnerabilities, follow the [Security Policy](../SECURITY.md).
