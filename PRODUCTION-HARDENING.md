# ROAR Protocol — Production Hardening Guide

**Version:** 0.3 (SDKs)
**Date:** 2026-03-16

This document covers deployment configuration, security settings, and operational practices required to run ROAR Protocol components safely in production. Development defaults are intentionally permissive; production deployments require explicit hardening.

---

## 1. Deployment Checklist

Work through this list before exposing any ROAR component to a network.

| # | Item | Default | Required Action |
|---|------|---------|----------------|
| 1 | **`signing_secret` strength** | `""` (empty) | Set to a strong random value of at least 32 bytes (256 bits). Use `python -c "import secrets; print(secrets.token_hex(32))"` |
| 2 | **Bind address** | `0.0.0.0` (all interfaces) | Bind ROARServer/ROARHub to `127.0.0.1` behind a reverse proxy, or restrict with firewall rules |
| 3 | **TLS termination** | None (plain HTTP) | Place ROARHub and ROARServer behind nginx or Caddy with a valid TLS certificate. Never expose plain HTTP to the public internet |
| 4 | **`SESSION_SECRET`** | Not set | Set a strong random value in environment; rotate periodically (at minimum, on any suspected compromise) |
| 5 | **Token store** | `InMemoryTokenStore` | Use `RedisTokenStore` for all multi-worker deployments (see Section 3) |
| 6 | **Migration check** | Skip by default | Set `PROWLRBOT_SKIP_MIGRATION_CHECK=false` in production to ensure schema migrations are applied at startup |
| 7 | **Ingest services** | `SKIP_INGEST_SERVICES=true` | Set to `false` only after configuring all required message brokers; do not enable with missing broker config |
| 8 | **Process supervisor** | None | Use systemd, pm2, or supervisord — never run bare `uvicorn` in production without a restart policy |
| 9 | **Log rotation** | None | Configure logrotate or equivalent to prevent log files from exhausting disk. Rotate daily, retain 30 days compressed |
| 10 | **`SECRET_STORE_MASTER_KEY`** | Not set | Pin to exactly 32 ASCII characters. Generate with `python -c "import secrets; print(secrets.token_urlsafe(32)[:32])"` |

---

## 2. Security Configuration

### 2.1 Body Size Limits

ROAR components enforce request body size limits to prevent memory exhaustion attacks:

| Component | Default Limit | Configuration |
|-----------|-------------|--------------|
| ROARServer | 1 MiB (1,048,576 bytes) | Set `MAX_BODY_SIZE` env var or configure in server constructor |
| ROARHub | 256 KiB (262,144 bytes) | Hub enforces a stricter limit because discovery payloads are smaller |

To set a custom limit in nginx (recommended — enforce at the proxy before the app sees the bytes):

```nginx
client_max_body_size 1m;  # For ROARServer upstream
```

### 2.2 Rate Limiting

ROAR includes built-in Redis-backed rate limiting via `roar_sdk.middleware.rate_limiter.RateLimiterMiddleware`. It supports per-IP dual sliding windows (per-minute and per-hour), configurable via environment variables (`RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_PER_HOUR`). The middleware degrades gracefully if Redis is unavailable. For defense in depth, also configure rate limiting at the proxy layer.

Example nginx configuration for the registration endpoint (the most abuse-prone):

```nginx
limit_req_zone $binary_remote_addr zone=roar_register:10m rate=5r/m;

location /register {
    limit_req zone=roar_register burst=10 nodelay;
    proxy_pass http://127.0.0.1:8000;
}

location / {
    limit_req zone=roar_register burst=100 nodelay;
    proxy_pass http://127.0.0.1:8000;
}
```

Tune `rate` and `burst` for your expected agent fleet size.

### 2.3 Replay Protection Window

The SDK enforces two independent replay protection mechanisms:

| Mechanism | Window | Scope |
|-----------|--------|-------|
| Timestamp check | 300 seconds (5 minutes) | Signed — attacker cannot modify without breaking HMAC |
| Message ID dedup (`IdempotencyGuard`) | 600 seconds (10 minutes) | Catches slow replays and concurrent submission to the same worker |

The two windows overlap intentionally: the ID dedup window is longer than the timestamp window, so any message that passes the timestamp check can still be caught by ID dedup if it is a replay submitted within the dedup TTL.

To adjust (not recommended without understanding the trade-offs):

```python
from roar_sdk.dedup import IdempotencyGuard

# Extend dedup window to 30 minutes for high-latency networks
guard = IdempotencyGuard(max_keys=50_000, ttl_seconds=1800.0)
```

### 2.4 Nonce Store Sizing

The default `IdempotencyGuard` capacity is `max_keys=10,000` with LRU eviction. Memory consumption is approximately:

```
10,000 keys × (avg_key_len + 8 bytes timestamp) ≈ ~1.5 MiB
```

For high-throughput hubs (>10,000 unique messages per 10-minute window), increase `max_keys`:

```python
guard = IdempotencyGuard(max_keys=100_000, ttl_seconds=600.0)
```

This uses approximately 15 MiB. The LRU eviction policy ensures memory is bounded.

---

## 3. Multi-Worker Safety

### 3.1 The Problem with InMemoryTokenStore

`InMemoryTokenStore` (the default for both delegation token use-counts and the `IdempotencyGuard`) maintains state in a Python `dict` or `OrderedDict` within a single process. When you run multiple uvicorn workers or gunicorn processes:

- Each worker has its own isolated copy of the token store.
- A `DelegationToken` with `max_uses=1` submitted to two workers simultaneously will be accepted by both, because each worker sees `use_count=0`.
- An `IdempotencyGuard` cannot deduplicate a replay if the replay lands on a different worker than the original.

**Do not use InMemoryTokenStore in any multi-worker deployment.**

### 3.2 Redis Connection Configuration

Install the Redis extra:

```bash
pip install 'roar-sdk[server]' redis
```

Configure using an environment variable:

```bash
export ROAR_REDIS_URL="redis://:your_password@redis-host:6379/0"
# For TLS-encrypted Redis (Redis Cloud, ElastiCache with TLS):
export ROAR_REDIS_URL="rediss://:your_password@redis-host:6380/0"
```

Example `RedisTokenStore` connection in application code:

```python
import redis
from roar_sdk.server import ROARServer

r = redis.from_url(
    "redis://:your_password@redis-host:6379/0",
    decode_responses=True,
    socket_timeout=2.0,
    socket_connect_timeout=2.0,
)
server = ROARServer(token_store=RedisTokenStore(r))
```

### 3.3 Atomic Counter Approach (INCR)

`RedisTokenStore` uses Redis's atomic `INCR` command for `use_count` tracking:

```
INCR tok:<token_id>:use_count
```

`INCR` is atomic at the Redis server level — even under concurrent requests from many workers, the counter is incremented exactly once per call. The returned new value determines whether the token's `max_uses` limit has been reached:

```python
new_count = redis.incr(f"tok:{token_id}:use_count")
if new_count > token.max_uses:
    redis.decr(f"tok:{token_id}:use_count")  # rollback
    return False  # token exhausted
```

This eliminates the race condition present in the in-memory `consume()` implementation.

---

## 4. did:web Security

The `did_web.py` resolver includes multiple defenses against SSRF and abuse:

### 4.1 HTTPS Required

The resolver rejects any `did:web` DID that would resolve to a plain HTTP URL. Only `https://` scheme URLs are accepted. This is enforced before the DNS lookup occurs.

```python
# did:web:example.com → https://example.com/.well-known/did.json  ✓
# did:web:http:example.com → rejected (malformed DID, not HTTPS)  ✗
```

### 4.2 Private IP SSRF Protection

Before establishing a connection, the resolver resolves the hostname to IP addresses and checks each against blocked ranges:

| Blocked Range | Purpose |
|--------------|---------|
| `127.0.0.0/8` | IPv4 loopback |
| `10.0.0.0/8` | RFC 1918 private |
| `172.16.0.0/12` | RFC 1918 private |
| `192.168.0.0/16` | RFC 1918 private |
| `169.254.0.0/16` | IPv4 link-local (AWS IMDS, GCP metadata) |
| `::1` | IPv6 loopback |
| `fc00::/7` | IPv6 ULA (Unique Local Addresses) |
| `fe80::/10` | IPv6 link-local |

This protection is **enabled by default** and cannot be disabled via configuration.

**Limitation:** DNS rebinding attacks are not mitigated by IP blocking alone. The hostname is resolved at connection initiation time, but a malicious DNS server could return a public IP for the initial check and then return an internal IP before the actual TCP connection. Mitigate with an egress firewall on the host running ROARHub.

### 4.3 Response Size Cap

DID document fetch responses are truncated at 64 KiB (65,536 bytes). Any response larger than this is rejected with an error. This prevents memory exhaustion from a server returning a multi-megabyte response to a resolution request.

### 4.4 Timeout

DID resolution has a 5-second default timeout covering both connection establishment and full response receipt. Configure with the `DID_WEB_TIMEOUT_SECONDS` environment variable if your network topology requires a longer timeout.

---

## 5. Known Operational Risks

### 5.1 Hub Registration Authentication (Current)
As of v0.3, hub registration uses challenge-response authentication. An agent must prove control of its DID by signing a challenge with its Ed25519 private key before its `AgentCard` is accepted into the directory. This replaces the v0.2 unauthenticated registration.

### 5.2 Hub-to-Hub Federation Sync (Accepted Risk)
Inter-hub federation sync is authenticated at the channel level using a shared secret but individual agent cards received via federation are **not** independently signed by the originating agent. A compromised federation peer hub can inject fabricated agent cards into the receiving hub's directory. Planned mitigation: per-card Ed25519 signatures in the v0.4 federation specification.

### 5.3 did:roar: DID Method Not Resolvable Without a Registry
`did:roar:` DIDs are self-issued identifiers that cannot be resolved to a DID document without a running ROAR registry or hub. Identity verification for `did:roar:` agents relies on the hub's local SQLite directory. There is no universal, offline-verifiable resolution path for this DID method.

---

## 6. Security Tool Baseline

*Results captured on 2026-03-16 against roar-sdk v0.3.0, Python 3.13.9.*

### 6.1 Bandit — Python AST Security Scan

Command:
```bash
bandit -r python/src/roar_sdk/ -ll --skip B104,B107 -f txt
```

Result: **No issues identified at MEDIUM or HIGH severity.**

```
Run metrics:
    Total issues (by severity):
        Undefined: 0
        Low: 1
        Medium: 0
        High: 0
    Total issues (by confidence):
        Undefined: 0
        Low: 0
        Medium: 0
        High: 1
Files skipped (0)
```

The single Low-severity finding (not shown at `-ll` threshold) relates to `assert` statements in test code. The two skipped rules:
- **B104** (`hardcoded-bind-all-interfaces`): Intentional for `ROARHub`, which binds `0.0.0.0` by default and documents that a reverse proxy is required in production.
- **B107** (`hardcoded-password-default`): The `signing_secret=""` default is an explicitly documented optional argument, not a credential embedded in code.

### 6.2 pip-audit — Dependency Vulnerability Scan

Command:
```bash
pip-audit --desc --local --skip-editable
```

Findings relevant to roar-sdk's declared dependency tree (`pydantic`, `cryptography`, `httpx`, `fastapi`, `uvicorn`, `websockets`):

| Package | Version | CVE | Fix Version | Assessment |
|---------|---------|-----|-------------|-----------|
| `cryptography` | 45.0.7 | CVE-2026-26007 | 46.0.5 | **Not exploitable** — affects SECT curves only (binary-field curves). ROAR Protocol uses Ed25519, which is defined over a prime-order curve (`edwards25519`). No ECDH or ECDSA over SECT curves is used anywhere in the SDK. |

No other roar-sdk direct dependencies had findings. The full audit flagged many system-level packages (aiohttp, django, flask, pillow, etc.) that are not part of roar-sdk's dependency graph; those findings are the responsibility of the system Python environment, not this project.

**Recommended action:** Pin `cryptography>=46.0.5` in `pyproject.toml` as a precaution when 46.x is released and tested against the SDK. Monitor for compatibility with the Ed25519 API used in `signing.py` and `delegation.py`.

---

## 6. Secrets Management

### 6.1 Generating Secrets

Use the CLI to generate all required secrets:

```bash
# Generate both HMAC and Ed25519 keys
roar keygen --type both

# Output:
# ROAR_SIGNING_SECRET=<base64url random>
# ROAR_ED25519_PRIVATE_KEY=<64 hex chars>
# ROAR_ED25519_PUBLIC_KEY=<64 hex chars>

# Write directly to .env file
roar keygen --type both --output .env
```

Or generate manually:

```bash
# HMAC secret (minimum 32 bytes / 256 bits)
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Ed25519 keypair
python -c "from roar_sdk.signing import generate_keypair; priv, pub = generate_keypair(); print(f'PRIVATE={priv}\nPUBLIC={pub}')"
```

### 6.2 Environment Variables

Store secrets in environment variables, never in source code. Use a `.env` file for local development (see `.env.example`):

| Variable | Purpose | Required |
|----------|---------|:--------:|
| `ROAR_SIGNING_SECRET` | HMAC-SHA256 message signing | Yes |
| `ROAR_FEDERATION_SECRET` | Hub-to-hub federation auth | If using federation |
| `ROAR_REDIS_URL` | Redis connection for token store | If multi-worker |
| `ROAR_ED25519_PRIVATE_KEY` | Ed25519 private key (hex) | If using Ed25519 |
| `ROAR_ED25519_PUBLIC_KEY` | Ed25519 public key (hex) | If using Ed25519 |

### 6.3 Key Rotation

ROAR supports zero-downtime key rotation via `KeyTrustStore`:

1. Generate a new key: `roar keygen --type ed25519`
2. Register the new key in the trust store — old key enters a grace period
3. During the grace period, both old and new keys are accepted
4. After the grace period (default: 24 hours), the old key expires automatically

```python
from roar_sdk.key_trust import KeyTrustStore

store = KeyTrustStore(rotation_grace_hours=24)
store.register_key(agent.did, old_public_key)

# Later, rotate:
store.rotate_key(agent.did, new_public_key)
# Old key stays valid for 24h, then auto-expires
```

### 6.4 What Not to Do

- Never commit `.env` files (already in `.gitignore`)
- Never hardcode secrets in source code — use `os.environ.get()`
- Never log secret values — log key IDs or fingerprints instead
- Never send private keys over the network — only public keys travel in AgentIdentity
- Never accept public keys from message `auth` headers — always resolve from a trusted source (DID Document, hub registry)
