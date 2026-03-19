# ROAR Protocol — Threat Model

**Version:** 0.3 (spec) / 0.3 (SDKs)
**Date:** 2026-03-16
**Scope:** ROAR Protocol specification, Python SDK, TypeScript SDK, ROARHub discovery server

---

## 1. Actors

### 1.1 Legitimate Registered Agents (Trusted)
Agents that have registered with a ROARHub, possess a valid HMAC signing secret or Ed25519 keypair, and operate within their declared capabilities. These agents are the expected participants in the protocol.

### 1.2 Malicious Agents with Valid HMAC Secrets (Insider Threat)
Agents that have legitimately obtained a signing secret (e.g., a shared team secret or a secret stolen from a misconfigured environment) but use it to craft messages that exceed their authorized capabilities, impersonate other agents, or replay captured messages. The symmetric nature of HMAC means possession of the secret is sufficient to forge any message on that channel.

### 1.3 External Unauthenticated Attackers (No Secret)
Network-level attackers who can send arbitrary HTTP requests to ROARHub or ROARServer endpoints but do not possess a valid signing secret or private key. Their attack surface is limited to unauthenticated endpoints (discovery, agent card lookup, registration) and transport-layer abuse.

### 1.4 Compromised Agents (Valid Identity, Privilege Escalation)
Agents with a legitimate DID and signing key but whose runtime has been compromised (e.g., prompt injection, supply-chain attack on dependencies). They attempt to acquire capabilities beyond their delegation scope, forge delegation tokens, or abuse the DID resolution path for SSRF.

### 1.5 Federation Peer Hubs (Semi-Trusted)
Remote ROARHub instances that participate in inter-hub federation. They are trusted to forward valid agent registrations but are not fully trusted: a compromised or malicious peer hub could inject fabricated agent cards or relay replayed messages.

---

## 2. Trust Boundaries

```
[External Internet]
       |
       | HTTPS (TLS termination — nginx/caddy)
       v
[Transport Boundary 1] ─────────────────────────────────────────────
       |
       | HTTP request with Authorization / X-ROAR-Signature header
       v
[HMAC Authentication Boundary 2] ───────────────────────────────────
       |
       | Verified shared secret, timestamp window, ID dedup
       v
[DID Identity Boundary 3] ──────────────────────────────────────────
       |
       | Ed25519 public key proof — from_identity.did matches public_key
       v
[Delegation Scope Boundary 4] ──────────────────────────────────────
       |
       | delegate_did bind, capabilities list, expiry, max_uses
       v
[Application Logic]
       |
       | Federation sync (outbound to peer hubs)
       v
[Federation Boundary 5] ────────────────────────────────────────────
       |
       | Shared secret or signed agent cards (hub-to-hub)
       v
[Peer ROARHub]
```

### Boundary Descriptions

| # | Boundary | Enforcement Point | Protocol Mechanism |
|---|----------|------------------|-------------------|
| 1 | Transport | Reverse proxy (nginx/caddy) | TLS — plaintext HTTP is rejected |
| 2 | HMAC authentication | `ROARMessage.verify()` | HMAC-SHA256 over 7 canonical fields, 300 s timestamp window, 600 s ID dedup |
| 3 | DID identity | `verify_ed25519()` | Ed25519 signature verified against `from_identity.public_key` |
| 4 | Delegation scope | `verify_token()` + `DelegationToken.grants()` | Ed25519-signed token: `delegate_did`, `capabilities`, `expires_at`, `max_uses` |
| 5 | Federation | Hub registration endpoint | Challenge-response authentication (hub registration); federation sync uses shared secret |

---

## 3. Attack Vectors

### 3.1 Replay Attack

**Description:** An attacker captures a valid, authenticated ROAR message (e.g., via network sniffing on a misconfigured non-TLS endpoint) and re-submits it to the server to repeat an action.

| Property | Value |
|----------|-------|
| Likelihood | Medium — requires network position or TLS stripping |
| Impact | High — repeated execution of tool calls, duplicate billing, nonce reuse |

**Mitigations in place:**
- `auth.timestamp` is embedded in the signed canonical body; messages older than 300 seconds are rejected by `verify()`.
- `IdempotencyGuard` tracks message IDs with a 600-second TTL (separate, longer window to catch slow replays). Default capacity: 10,000 keys with LRU eviction.
- Both the timestamp and the message ID are covered by the HMAC signature — an attacker cannot update them without breaking the signature.

**Residual risk:** In a multi-worker deployment using `InMemoryTokenStore` or the default in-process `IdempotencyGuard`, the dedup set is not shared across workers. A message replayed to a different worker within the TTL window will be accepted. Use `RedisTokenStore` (see PRODUCTION-HARDENING.md).

---

### 3.2 Token Theft

**Description:** An attacker obtains another agent's HMAC signing secret or Ed25519 private key (e.g., through an exposed environment variable, log file, or misconfigured secret store) and uses it to sign messages as that agent.

| Property | Value |
|----------|-------|
| Likelihood | Medium — environment variable leakage is common in CI/CD |
| Impact | Critical — complete impersonation of the victim agent |

**Mitigations in place:**
- Secrets should be stored in environment variables, not source code (documented in PRODUCTION-HARDENING.md).
- HMAC signing secrets are never transmitted over the wire — only the resulting signature is sent.
- Ed25519 private keys are never embedded in agent cards — only the public key is published.

**Residual risk:** HMAC is symmetric. If the shared secret is compromised, all agents sharing that secret are affected simultaneously. There is no per-agent revocation mechanism. Key rotation requires restarting all agents with a new secret.

---

### 3.3 Confused Deputy

**Description:** An attacker submits a ROAR message containing a delegation token where the `delegator_did` points to a high-privilege agent but the token was signed with the attacker's own private key. The verifier must not trust `delegator_did` as an authority without verifying the signature against the delegator's registered public key.

| Property | Value |
|----------|-------|
| Likelihood | Low — requires understanding of the delegation protocol |
| Impact | High — privilege escalation to delegator's capabilities |

**Mitigations in place:**
- `verify_token(token, delegator_public_key)` requires the caller to supply the delegator's public key explicitly.
- The delegator's public key must be obtained from the trusted agent registry (hub), not from the token itself.
- The token's `delegator_did` and `delegate_did` are both covered by the Ed25519 signature — any mismatch invalidates the signature.

**Residual risk:** If the server retrieves `delegator_public_key` from the token's own `delegator_did` field without checking the registry, the verification is trivially bypassed. Implementers must look up the public key independently.

---

### 3.4 Delegation Forgery

**Description:** An attacker attempts to create a `DelegationToken` granting capabilities they do not possess, by constructing the JSON body and providing any signature.

| Property | Value |
|----------|-------|
| Likelihood | Low — requires cryptographic forgery or key compromise |
| Impact | High — unauthorized capability grant |

**Mitigations in place:**
- Delegation tokens are signed with the delegator's Ed25519 private key using a deterministic canonical JSON body (`sort_keys=True` over all token fields).
- `verify_token()` verifies the Ed25519 signature over `capabilities`, `delegate_did`, `delegator_did`, `expires_at`, `issued_at`, `max_uses`, `token_id`, and `can_redelegate`.
- Re-delegation is gated by `can_redelegate: bool` — a delegate cannot issue sub-tokens unless explicitly permitted.

**Residual risk:** Token forgery is only possible if the delegator's Ed25519 private key is compromised (see 3.2). The Python SDK provides `KeyTrustStore` for key rotation with a grace period, but there is no spec-level key revocation mechanism.

---

### 3.5 Algorithm Confusion

**Description:** An attacker strips the `hmac-sha256:` prefix from a valid signature and re-submits the message with a different `auth.signature` value, hoping the verifier falls back to an unsigned or weaker algorithm.

| Property | Value |
|----------|-------|
| Likelihood | Low — requires knowledge of the verification code path |
| Impact | High — authentication bypass |

**Mitigations in place:**
- `ROARMessage.verify()` checks that `auth.signature` begins with exactly `"hmac-sha256:"` before proceeding. Missing or empty signatures return `False` immediately.
- `verify_ed25519()` checks that `auth.signature` begins with exactly `"ed25519:"`. There is no fallback to any other algorithm.
- The two verification functions are entirely separate code paths — there is no auto-detect that could be tricked into choosing the weaker algorithm.

**Residual risk:** Callers that do not check the `signature` prefix before branching between `verify()` and `verify_ed25519()` could be vulnerable. Document in integration guidelines.

---

### 3.6 Hub Poisoning

**Description:** An external attacker or malicious agent submits a forged `AgentCard` to the ROARHub discovery directory, registering a fake agent with elevated declared capabilities. Legitimate agents that query the directory may route messages to the fake agent.

| Property | Value |
|----------|-------|
| Likelihood | Medium — hub registration endpoints may be publicly accessible |
| Impact | Medium — misdirected messages, capability fraud in discovery |

**Mitigations in place:**
- Hub registration uses a challenge-response authentication mechanism (as of v0.3).
- Agent cards do not grant capabilities directly — capabilities are enforced by the receiving server, not the directory.
- The hub can be configured to require a signed agent card (Ed25519 signature from the registering agent's DID).

**Residual risk:** The SQLite-backed `AgentDirectory` has no built-in rate limiting on registration. An attacker with any valid credential can flood the directory. Configure nginx rate limiting on `/register` endpoints.

---

### 3.7 Federation Injection

**Description:** A malicious or compromised federation peer hub sends fabricated agent registrations during a hub-to-hub sync. The receiving hub blindly adds these to its local directory.

| Property | Value |
|----------|-------|
| Likelihood | Medium — hub-to-hub federation sync relies on shared secrets |
| Impact | Medium — poisoned discovery directory, misdirected traffic |

**Mitigations in place:**
- Hub-to-hub federation uses a shared secret for authentication of the sync channel.
- Agent cards received from federated hubs are stored with their originating `hub_url` tag, allowing targeted purging.

**Residual risk:** Federation sync is not yet verified with per-card signatures. A compromised federation peer can inject any agent card into the directory. This is a known accepted risk (see Section 5 — Known Limitations).

---

### 3.8 SSRF via did:web Resolution

**Description:** An attacker supplies a `did:web` DID that resolves to an internal metadata endpoint (e.g., `http://169.254.169.254/latest/meta-data/` on AWS). When the hub attempts to resolve the DID document, it fetches the internal URL, leaking credentials or internal topology.

| Property | Value |
|----------|-------|
| Likelihood | Medium — did:web accepts attacker-supplied hostnames by design |
| Impact | High — cloud IMDS credential leakage, internal service access |

**Mitigations in place:**
- The `did_web.py` resolver enforces HTTPS-only — plain HTTP URLs are rejected at the resolver level.
- Private IP ranges (RFC 1918: 10.x, 172.16-31.x, 192.168.x; loopback 127.x; link-local 169.254.x; IPv6 equivalents) are blocked before DNS resolution.
- Response size is capped at 64 KiB to prevent memory exhaustion.
- Resolution has a 5-second timeout to limit resource consumption.

**Residual risk:** DNS rebinding attacks (attacker owns a domain that resolves to a public IP at HTTPS handshake time, then rebinds to an internal IP) are not mitigated by IP blocking alone. Use an egress firewall to prevent the hub process from making outbound connections to internal networks.

---

### 3.9 Message ID Collision

**Description:** An attacker crafts two distinct messages with identical `id` fields. If the dedup store records the first and the second arrives shortly after, only the first is processed. Alternatively, the attacker crafts a message with a known-good ID from a recent legitimate message to force deduplication of the legitimate follow-up.

| Property | Value |
|----------|-------|
| Likelihood | Low — `msg_` prefix + 40-bit random hex gives ~1 trillion IDs |
| Impact | Low — at most, denial of one message in the 600 s window |

**Mitigations in place:**
- Message IDs are generated as `msg_<uuid4().hex[:10]>` — sufficiently random for practical uniqueness.
- The HMAC covers the `id` field — an attacker cannot copy a legitimate ID without also copying the entire message (making it a replay, covered by 3.1).

**Residual risk:** Benign ID collisions across a very large fleet within the 600 s dedup window are possible but extremely unlikely. The LRU eviction at `max_keys=10,000` ensures the guard does not grow unbounded.

---

### 3.10 Multi-Worker Token Double-Spend

**Description:** A delegation token with `max_uses=1` is submitted concurrently to two different server workers. Each worker's in-memory `use_count` is zero at the time of check, so both workers accept the token and increment their local counter. The token is effectively used twice.

| Property | Value |
|----------|-------|
| Likelihood | High — any multi-worker uvicorn/gunicorn deployment is vulnerable by default |
| Impact | Medium — token use limit bypassed; severity depends on what the capability controls |

**Mitigations in place:**
- Single-worker deployments (the default for development) are not vulnerable — token state is process-local and serialized.
- The documentation recommends `RedisTokenStore` with INCR-based atomic counters for multi-worker deployments.

**Residual risk:** The Python SDK ships `InMemoryTokenStore` as the default. There is no runtime warning or assertion if multiple workers share a process space. See PRODUCTION-HARDENING.md for the Redis migration guide.

---

## 4. Security Properties Claimed

| Property | Mechanism | Scope |
|----------|-----------|-------|
| **Authenticity** | HMAC-SHA256 over canonical 7-field body | Every ROARMessage exchanged between agents using a shared secret |
| **Integrity** | HMAC covers `id`, `from`, `to`, `intent`, `payload`, `context`, `timestamp` — any modification invalidates the signature | All 7 canonical fields |
| **Replay protection** | 300 s timestamp window (signed) + 600 s message ID dedup (IdempotencyGuard) | Per-process; see multi-worker caveat |
| **Authorization** | `delegate_did` bind check ensures token can only be used by its intended recipient; `capabilities` list limits scope | DelegationToken path |
| **Delegation integrity** | Ed25519 signature over all token fields using delegator's private key | DelegationToken issuance and verification |

---

## 5. Known Limitations and Accepted Risks

### 5.1 did:roar: DIDs Not Resolvable Without a Registry
`did:roar:` DIDs are self-issued and cannot be resolved to a DID document without a running ROAR registry. Identity verification for `did:roar:` agents relies on the hub's local agent directory, not a universally accessible registry. This limits cross-deployment identity portability.

### 5.2 In-Memory Token Stores Not Safe Across Workers
`InMemoryTokenStore` and the default `IdempotencyGuard` maintain state within a single process. Multi-worker deployments (gunicorn, multiple uvicorn instances) must use `RedisTokenStore`. This is documented but not enforced at runtime. See PRODUCTION-HARDENING.md Section 3.

### 5.3 Symmetric HMAC — Key Compromise Affects All Sharing Agents
HMAC-SHA256 uses a shared secret. Any party possessing the secret can forge messages as any other party using that secret. Key rotation requires coordinated restart of all agents. There is no per-agent key derivation or revocation in the current spec.

### 5.4 Ed25519 Key Rotation — Limited Support
The Python SDK provides `KeyTrustStore` with a configurable grace period for zero-downtime key rotation (see PRODUCTION-HARDENING.md §6.3). However, the `AgentIdentity.public_key` field holds a single key, and there is no spec-level mechanism to publish key history or revoke a compromised key without re-registering the agent with a new DID.

### 5.5 Federation Sync Not Per-Card Signed
Hub-to-hub federation sync is authenticated at the channel level (shared secret) but individual agent cards received via federation are not independently signed by the originating agent. A compromised federation peer can inject arbitrary agent cards. Accepted risk pending a v0.4 federation signing specification.

### 5.6 Rate Limiting
The Python SDK includes built-in Redis-backed rate limiting via `roar_sdk.middleware.rate_limiter.RateLimiterMiddleware` (per-IP dual sliding windows). The TypeScript SDK includes rate limiting in its native HTTP router. For defense in depth, also configure rate limiting at the reverse proxy layer (see PRODUCTION-HARDENING.md §2.2).
