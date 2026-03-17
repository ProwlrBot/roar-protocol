# DNS-Based Agent Discovery

> **Status: Experimental** — This feature implements the IETF BANDAID concept for discovering ROAR agents and hubs via DNS. The implementation is functional but the underlying IETF draft is not yet finalized.

---

## Overview

ROAR agents need to find each other. Local directories and hub federation work great within known infrastructure, but what about discovering agents across organizations? DNS-based discovery lets agents find each other using the internet's existing name system — no central registry required.

The implementation supports **three discovery standards** and a multi-strategy resolution chain that tries each in priority order.

---

## Discovery Standards

### 1. DNS-AID (IETF BANDAID Successor)

Uses SVCB and TXT records at `_agents.{domain}` to advertise a ROAR hub.

```
_agents.example.com. 3600 IN SVCB 1 hub.example.com. alpn="h2,h3" port="8090"
_agents.example.com. 3600 IN TXT "v=roar1" "hub=https://hub.example.com:8090" "caps=code-review,testing"
```

- **SVCB records** (RFC 9460) are the modern replacement for SRV, supporting ALPN negotiation and encrypted transport hints.
- **TXT records** carry structured metadata: protocol version (`v=roar1`), hub URL, and aggregate capabilities.

### 2. did:web Publishing

Publishes a W3C DID Document at `/.well-known/did.json` with service endpoints pointing to the hub.

```json
{
  "@context": ["https://www.w3.org/ns/did/v1"],
  "id": "did:web:example.com",
  "service": [
    {
      "id": "did:web:example.com#svc-roar-hub",
      "type": "ROARHub",
      "serviceEndpoint": "https://hub.example.com:8090"
    },
    {
      "id": "did:web:example.com#agent-architect",
      "type": "ROARAgent",
      "serviceEndpoint": "https://hub.example.com:8090/roar/agents/did:roar:agent:architect-a1b2",
      "capabilities": ["code-review", "architecture"]
    }
  ]
}
```

### 3. ANP (Agent Network Protocol) JSON-LD

Publishes agent descriptions in JSON-LD format at `/.well-known/agent.json`.

```json
{
  "@context": ["https://www.w3.org/ns/activitystreams", {"roar": "https://roar-protocol.dev/ns/"}],
  "@type": "https://agentnetworkprotocol.com/ns/Agent",
  "@id": "did:roar:agent:architect-a1b2",
  "name": "architect",
  "summary": "Backend architect specializing in API design",
  "skills": [{"@type": "Skill", "name": "code-review"}],
  "endpoints": [{"@type": "Endpoint", "protocol": "roar", "url": "https://hub.example.com/roar/agents/..."}],
  "registeredHub": "https://hub.example.com:8090"
}
```

---

## Resolution Priority

When `discover_hub(domain)` is called, strategies are tried in order — first match wins:

| Priority | Strategy | Endpoint | Source Tag |
|:--------:|:---------|:---------|:-----------|
| 1 | DNS SRV | `_roar._tcp.{domain}` | `dns` |
| 2 | DNS-AID TXT | `_agents.{domain}` | `dns-aid` |
| 3 | Well-Known | `https://{domain}/.well-known/roar.json` | `well-known` |
| 4 | did:web | `https://{domain}/.well-known/did.json` | `did-web` |
| 5 | ANP | `https://{domain}/.well-known/agent.json` | `anp` |
| 6 | Manual URL | Caller-provided fallback | `manual` |

Results are cached with a **5-minute TTL** to reduce DNS and HTTP overhead.

---

## Usage

### Discovering a Hub

```python
from roar_sdk.dns_discovery import discover_hub

# Multi-strategy discovery
result = await discover_hub("example.com")
if result:
    print(f"Hub: {result.hub_url}")
    print(f"Source: {result.source}")  # e.g., "dns-aid", "well-known"
```

### Discovering Agents by Capability

```python
from roar_sdk.dns_discovery import discover_agents_dns

agents = await discover_agents_dns("example.com", capability="code-review")
for agent in agents:
    print(agent["display_name"], agent["capabilities"])
```

### With Manual Fallback

```python
result = await discover_hub(
    "example.com",
    manual_url="https://fallback-hub.example.com:8090"
)
```

---

## Publishing Your Hub

### Option A: DNS Records

Add these records to your DNS zone file. Use `generate_zone_file()` to generate them automatically:

```python
from roar_sdk.dns_discovery import generate_zone_file
from roar_sdk import AgentCard, AgentIdentity

agents = [
    AgentCard(
        identity=AgentIdentity(
            display_name="architect",
            capabilities=["code-review", "architecture"],
        ),
        description="Backend architect",
    ),
]

zone = generate_zone_file("example.com", "https://hub.example.com:8090", agents)
print(zone)
```

Output:

```dns
; ROAR Protocol DNS records for example.com
; Generated for hub: https://hub.example.com:8090
; Agents: 1
;
; --- DNS-AID (SVCB) records ---
_agents.example.com. 3600 IN SVCB 1 hub.example.com. alpn="h2,h3" port="8090"
_agents.example.com. 3600 IN TXT "v=roar1" "hub=https://hub.example.com:8090" "caps=code-review,architecture"
;
; --- Legacy SRV records ---
_roar._tcp.example.com. 3600 IN SRV 10 0 8090 hub.example.com.
_roar._tcp.example.com. 3600 IN TXT "v=roar1" "caps=code-review,architecture"
;
; --- Per-agent TXT records ---
architect._agents.example.com. 3600 IN TXT "did=did:roar:agent:architect-..." "caps=code-review,architecture" "desc=Backend architect"
```

### Option B: Well-Known Endpoint

Host a JSON file at `https://your-domain/.well-known/roar.json`:

```json
{
  "hub_url": "https://hub.example.com:8090",
  "version": "0.3.0",
  "agents": [
    {
      "did": "did:roar:agent:architect-a1b2c3d4",
      "display_name": "architect",
      "capabilities": ["code-review", "architecture"]
    }
  ]
}
```

### Option C: DID Document

Publish a W3C DID Document at `https://your-domain/.well-known/did.json`:

```python
from roar_sdk.dns_discovery import generate_did_document

doc = generate_did_document(
    "https://hub.example.com:8090",
    agent_cards=agents,
    domain="example.com",
    public_key="a1b2c3d4...",  # optional Ed25519 hex
)
# Host this at /.well-known/did.json
```

### Option D: ANP Description

Publish an ANP JSON-LD description at `https://your-domain/.well-known/agent.json`:

```python
from roar_sdk.dns_discovery import generate_anp_description

anp = generate_anp_description(agents[0], "https://hub.example.com:8090")
# Host this at /.well-known/agent.json
```

---

## Dependencies

| Feature | Required Package | Install |
|:--------|:-----------------|:--------|
| DNS SRV/TXT resolution | `dnspython` | `pip install dnspython` |
| HTTP-based discovery (well-known, did:web, ANP) | `httpx` | `pip install httpx` |
| Basic zone file generation | *(none)* | Built-in |

Both `dnspython` and `httpx` are **optional**. Without them, DNS lookups return empty results and HTTP strategies are skipped, but zone file generation and manual URLs still work.

---

## Security Considerations

### DNS Spoofing

DNS is inherently trust-on-first-use. Mitigations:

- **DNSSEC**: Deploy DNSSEC for your domain to prevent record tampering. Resolvers that validate DNSSEC will reject spoofed records.
- **TLS verification**: The well-known, did:web, and ANP strategies all use HTTPS, which provides server authentication via TLS certificates.
- **Hub authentication**: Even if discovery is spoofed, ROAR's message signing (HMAC-SHA256 / Ed25519) prevents an attacker from impersonating agents. A spoofed hub URL would fail at the signing verification step.

### Cache Poisoning

- The in-memory TTL cache (5 minutes) limits the window for stale/poisoned data.
- Production deployments SHOULD use a validating DNS resolver.

### Record Validation

- The resolver validates TXT record format (`v=roar1` prefix required).
- Hub URLs are validated as parseable URLs before use.
- DID Documents are checked for ROARHub/ROARMessaging service types.

### Recommendations

1. **Always deploy DNSSEC** for domains publishing ROAR DNS records.
2. **Use HTTPS** for all well-known endpoints (not HTTP).
3. **Pin hub certificates** in high-security deployments.
4. **Monitor DNS records** for unauthorized changes.
5. **Treat DNS discovery as a bootstrap mechanism** — once a hub is known, subsequent communication uses signed ROAR messages for authentication.

---

## Architecture

See [DIAGRAMS.md](DIAGRAMS.md#10-dns-based-discovery) for the visual flowchart of the multi-strategy resolution chain.

### How It Fits in the Stack

```
Layer 2: Discovery
├── AgentDirectory (local, in-memory)
├── SQLiteAgentDirectory (local, persistent)
├── ROARHub (federated, REST API)
└── DNS Discovery (cross-organization, experimental)
    ├── DNS-AID (SVCB/TXT at _agents.domain)
    ├── did:web (DID Documents at /.well-known/did.json)
    ├── ANP (JSON-LD at /.well-known/agent.json)
    └── Well-Known (JSON at /.well-known/roar.json)
```

DNS discovery is the **outermost ring** of the discovery system. Local directories are checked first, then hub federation, then DNS — ensuring the fastest path is always tried first.

---

## References

- [IETF BANDAID Draft](https://datatracker.ietf.org/doc/draft-mozleywilliams-dnsop-dnsaid/) — DNS-based Agent Identification
- [RFC 9460](https://www.rfc-editor.org/rfc/rfc9460) — SVCB and HTTPS Resource Records
- [W3C did:web Method](https://w3c-ccg.github.io/did-method-web/) — Domain-bound DIDs
- [ANP Specification](https://agentnetworkprotocol.com) — Agent Network Protocol
- [ROAR Spec: Layer 2](../spec/02-discovery.md) — Discovery layer specification

---

<p align="center">
  <sub>DNS discovery is experimental. The IETF BANDAID draft may change.</sub><br/>
  <sub>Implementation: <code>python/src/roar_sdk/dns_discovery.py</code></sub>
</p>
