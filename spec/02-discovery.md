# Layer 2: Discovery

> Decentralized agent directory, capability search, agent cards, matchmaking

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT",
"SHOULD", "SHOULD NOT", "RECOMMENDED", "MAY", and "OPTIONAL" in this
document are to be interpreted as described in RFC 2119.

---

## Overview

The Discovery layer enables agents to find each other based on capabilities, not hardcoded addresses. Agents register their capabilities via **Agent Cards**, and other agents search the directory to find collaborators.

The Discovery layer provides:
- **Agent Cards** — rich capability descriptors combining identity + skills + endpoints
- **Agent Directory** — in-memory registry for local discovery
- **Capability Search** — find agents that can perform specific tasks
- **Federation** — directories can sync across hubs for cross-machine discovery

---

## Agent Card

An Agent Card is the public-facing descriptor of an agent. Think of it as a business card that other agents can read to decide whether to collaborate.

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `identity` | AgentIdentity | REQUIRED | The agent's identity (Layer 1) |
| `description` | string | RECOMMENDED | What this agent does in plain English |
| `skills` | string[] | RECOMMENDED | Named skills this agent has installed |
| `channels` | string[] | OPTIONAL | Communication channels (console, discord, telegram) |
| `endpoints` | dict | OPTIONAL | Connection endpoints (`{"http": "http://...", "ws": "ws://..."}`) |
| `declared_capabilities` | AgentCapability[] | OPTIONAL | Formal capability declarations with schemas |
| `metadata` | dict | OPTIONAL | Arbitrary key-value metadata |

---

## Wire Format

### AgentCard

```json
{
  "identity": {
    "did": "did:roar:agent:architect-a1b2c3d4",
    "display_name": "architect",
    "agent_type": "agent",
    "capabilities": ["python", "api", "architecture"],
    "version": "1.0"
  },
  "description": "Backend architect specializing in API design and database schemas",
  "skills": ["code_review", "api_design", "db_migration"],
  "channels": ["console"],
  "endpoints": {
    "http": "http://localhost:8088/api/agent/architect"
  },
  "declared_capabilities": [
    {
      "name": "code_review",
      "description": "Review code for quality and security",
      "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}},
      "output_schema": {"type": "object", "properties": {"issues": {"type": "array"}}}
    }
  ],
  "metadata": {
    "team": "backend",
    "timezone": "America/New_York"
  }
}
```

### DiscoveryEntry

```json
{
  "agent_card": { "...AgentCard..." },
  "registered_at": 1710000000.0,
  "last_seen": 1710003600.0,
  "hub_url": "http://localhost:8099"
}
```

---

## Examples

### Register an agent

```python
from roar_sdk import AgentIdentity, AgentCard, AgentDirectory

directory = AgentDirectory()

card = AgentCard(
    identity=AgentIdentity(
        display_name="architect",
        capabilities=["python", "api", "architecture"],
    ),
    description="Backend architect",
    skills=["code_review", "api_design"],
)

entry = directory.register(card)
print(entry.agent_card.identity.did)
```

### Search by capability

```python
python_agents = directory.search("python")
for entry in python_agents:
    print(f"{entry.agent_card.identity.display_name}: {entry.agent_card.description}")
```

### Lookup by DID

```python
entry = directory.lookup("did:roar:agent:architect-a1b2c3d4")
if entry:
    print(entry.agent_card.description)
```

---

## Hub API Endpoints (Normative)

Implementations MUST expose the following endpoints on a ROARHub:

### GET /roar/health

Returns hub health status. No authentication required.

**Response:**

```json
{
  "status": "healthy",
  "protocol": "roar/1.0",
  "hub_url": "http://hub.example.com:8099",
  "agents": 42,
  "peers": 3,
  "dependencies": {
    "redis": "connected"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | MUST be `"healthy"` if the hub is operational |
| `protocol` | string | MUST be `"roar/1.0"` |
| `agents` | int | Number of registered agents |
| `peers` | int | Number of federation peers |
| `dependencies.redis` | string | `"connected"`, `"disconnected"`, or `"not_configured"` |

### GET /roar/agents

List all registered agents, optionally filtered by capability.

**Query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `capability` | string | OPTIONAL. Filter agents by capability substring match |

**Response:** `{"agents": [AgentCard, ...]}` — array of matching agent cards.

### GET /roar/agents/{did}

Look up a single agent by DID. Returns the AgentCard or 404.

---

## Challenge-Response Registration (Normative)

Implementations MUST use a two-step challenge-response protocol for agent registration. This prevents unauthorized registration and ensures the registrant controls the claimed Ed25519 key pair.

### Step 1: Request Challenge — POST /roar/agents/register

The client sends its DID, public key, and agent card. The hub returns a cryptographic challenge.

**Request body:**

```json
{
  "did": "did:roar:agent:alice-a1b2c3d4",
  "public_key": "<ed25519-public-key-hex>",
  "card": { "...AgentCard..." }
}
```

**Response (200):**

```json
{
  "challenge_id": "<32-char-hex>",
  "nonce": "<64-char-hex>",
  "expires_at": 1710000030.0
}
```

| Field | Type | Description |
|-------|------|-------------|
| `challenge_id` | string | 32-character hex token identifying this challenge |
| `nonce` | string | 64-character hex random value the client MUST sign |
| `expires_at` | float | Unix timestamp; challenge expires after 30 seconds |

Hubs MUST limit pending challenges (RECOMMENDED: 1000 max). If the limit is reached, the hub MUST return 503 Service Unavailable.

### Step 2: Prove Ownership — POST /roar/agents/challenge

The client signs the nonce with its Ed25519 private key and returns the signature.

**Request body:**

```json
{
  "challenge_id": "<challenge_id from step 1>",
  "signature": "ed25519:<base64url-no-padding>"
}
```

**Verification:** The hub MUST:

1. Look up the pending challenge by `challenge_id`.
2. Verify the challenge has not expired (within 30 seconds of issuance).
3. Verify the Ed25519 signature over the raw nonce bytes using the public key from step 1.
4. On success: register the agent card and delete the challenge (preventing replay).
5. On failure: return 401 Unauthorized.

**Response (200):** `{"registered": true}`

Implementations MUST delete challenges immediately upon use to prevent replay attacks.

---

## Unregistration — DELETE /roar/agents/{did} (Normative)

Agents MAY unregister by proving ownership of their DID. The request body MUST contain a signed deletion proof.

**Request body:**

```json
{
  "did": "did:roar:agent:alice-a1b2c3d4",
  "signature": "ed25519:<base64url-no-padding>",
  "nonce": "<random-hex>",
  "timestamp": 1710000000.0
}
```

**Signed message format:** The signature MUST be computed over the exact string:

```
delete:{did}:{nonce}:{timestamp}
```

**Verification:** The hub MUST:

1. Verify the DID exists in the directory.
2. Verify the timestamp is within 60 seconds of the server's current time.
3. Verify the Ed25519 signature using the agent's registered public key.
4. On success: remove the agent and return `{"status": "removed", "did": "..."}`.
5. On failure: return 401 Unauthorized.

---

## Federation (Normative)

Hubs MAY federate with peer hubs to share agent registrations across organizational boundaries.

### Authentication

All federation endpoints MUST require authentication. Implementations MUST use a shared secret (`ROAR_FEDERATION_SECRET`) transmitted via the `Authorization: Bearer <secret>` header.

If no federation secret is configured, federation endpoints MUST return 503 Service Unavailable. Implementations MUST NOT fall back to unauthenticated federation.

### POST /roar/federation/sync

Accept a batch of DiscoveryEntry objects from a peer hub.

**Request body:**

```json
{
  "hub_url": "http://peer-hub.example.com:8099",
  "exported_at": 1710000000.0,
  "entries": [
    {
      "agent_card": { "...AgentCard..." },
      "registered_at": 1710000000.0,
      "last_seen": 1710003600.0,
      "hub_url": "http://peer-hub.example.com:8099"
    }
  ]
}
```

**Merge semantics:** Implementations MUST NOT overwrite locally-registered agents with federation data. Only new DIDs (not already in the local directory) SHOULD be imported.

**Response (200):** `{"imported": 5, "total": 10}`

### GET /roar/federation/export

Export all local entries for peer hubs to import. Same authentication required.

**Response (200):**

```json
{
  "hub_url": "http://this-hub.example.com:8099",
  "exported_at": 1710000000.0,
  "entries": [ "...DiscoveryEntry[]..." ]
}
```

---

## Request Body Size Limits (Normative)

Hub endpoints MUST enforce a maximum request body size of **256 KiB**. Requests exceeding this limit MUST be rejected with HTTP 413 Payload Too Large.

---

## Integration with ProwlrHub

ProwlrHub (the war room) maintains its own agent registry that maps to ROAR discovery:

| ProwlrHub Concept | ROAR Discovery Concept |
|-------------------|----------------------|
| Agent registration | Agent Card + Directory entry |
| `get_agents()` | `directory.list_all()` |
| Capabilities | `identity.capabilities` |
| Agent status | `entry.last_seen` + heartbeat |

When an agent connects to ProwlrHub via MCP, it's automatically registered in both the war room and the ROAR directory.
